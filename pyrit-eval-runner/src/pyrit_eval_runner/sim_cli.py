from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import aiohttp
import yaml

from pyrit_eval_runner.cli_utils import (
    _collect_evaluator_paths,
    _fail,
    _invoke_completion_hook,
    _json_default,
    _load_yaml,
    _setup_logging,
    build_thread_id_parser,
    inject_thread_id,
)
from pyrit_eval_runner.multi_turn_helpers import (
    configure_openai_settings,
    instantiate_per_objective_scorers,
    prepare_evaluator_specs,
)


def _parse_report_metadata(raw_metadata: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw_metadata:
        return None
    try:
        parsed = json.loads(raw_metadata)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for --report-metadata: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("--report-metadata must be a JSON object")
    return parsed


def _load_config(args: argparse.Namespace) -> Dict[str, Any]:
    cfg_path = Path(args.config).resolve()
    if not cfg_path.exists():
        _fail(f"Config not found: {cfg_path}")
    cfg = _load_yaml(cfg_path)
    cfg["__path__"] = cfg_path
    return cfg


async def run_simulation_async(args: argparse.Namespace) -> int:
    _setup_logging()
    configure_openai_settings(args)
    scorer_temperature: Optional[float] = args.scorer_temperature
    chat_model: Optional[str] = getattr(args, "openai_chat_model", None)

    cfg = _load_config(args)
    cfg_path = cfg["__path__"]

    try:
        report_metadata = _parse_report_metadata(args.report_metadata)
    except ValueError as exc:
        return _fail(str(exc))

    base_url = args.target_endpoint
    token = args.auth_token

    http_raw = cfg.get("http_request_raw")
    field_defs = cfg.get("field_defs")
    thread_id_pattern = cfg.get("thread_id_pattern")
    thread_id_key = cfg.get("thread_id_query_param_key", "threadId")
    strategy_path_value = args.strategy_path or cfg.get("strategy_path")
    objectives = cfg.get("objectives")
    use_score_as_feedback = bool(cfg.get("use_score_as_feedback", True))
    evaluate_chat = bool(cfg.get("evaluate_chat", False))
    include_history = bool(cfg.get("include_history", False))
    max_turns = int(cfg.get("max_turns", 5))
    max_retries = int(cfg.get("max_retries", 3))
    timeout_seconds = int(cfg.get("timeout_seconds", 300))
    successful_objective_threshold = float(cfg.get("successful_objective_threshold", 0.8))
    seed_prompt = cfg.get("seed_prompt", "")
    scorer_type = (os.getenv("PYRIT_SCORER_TYPE") or str(cfg.get("scorer_type", "float_scale"))).strip().lower()

    if not isinstance(objectives, list) or not objectives:
        return _fail("Config must include a non-empty 'objectives' list")
    if not isinstance(field_defs, list):
        return _fail("Config field_defs must be a list")
    if not http_raw:
        return _fail("Config must include http_request_raw")
    if not strategy_path_value:
        return _fail("Config must include strategy_path")
    if scorer_type not in ("float_scale", "true_false"):
        return _fail("scorer_type must be 'float_scale' or 'true_false'")

    if args.strategy_path:
        strategy_path = Path(args.strategy_path).expanduser().resolve()
    else:
        strategy_path = (cfg_path.parent / strategy_path_value).resolve()
    if not strategy_path.exists():
        return _fail(f"Strategy file not found: {strategy_path}")

    scorer_str = args.scorer
    try:
        scorer_json = json.loads(scorer_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for --scorer: {exc}")

    from pyrit_eval_runner.pyrit_init import ensure_pyrit_initialized_async

    # PyRIT must be initialized before we instantiate any scorers/targets because they
    # rely on the central memory singleton being set up.
    await ensure_pyrit_initialized_async()

    try:
        evaluator_paths = _collect_evaluator_paths(scorer_json)
    except ValueError as exc:
        return _fail(str(exc))

    if not evaluator_paths:
        return _fail("Config must include evaluator paths for scorers")

    try:
        target_kwargs: Dict[str, Any] = {}
        if scorer_temperature is not None:
            target_kwargs["temperature"] = scorer_temperature
        if chat_model:
            target_kwargs["model_name"] = chat_model

        evaluator_specs = prepare_evaluator_specs(
            evaluator_paths,
            scorer_type=scorer_type,
            openai_chat_target_kwargs=target_kwargs if target_kwargs else None,
        )
    except ValueError as exc:
        return _fail(str(exc))

    env_report_threshold = os.getenv("PYRIT_REPORT_THRESHOLD")
    if env_report_threshold is not None:
        report_threshold = float(env_report_threshold)
    elif "report_threshold" in cfg:
        report_threshold = float(cfg["report_threshold"])
    else:
        report_threshold = 0.8

    try:
        http_request_templated = str(http_raw).format(base_url=base_url, token=token)
    except KeyError as exc:
        return _fail(f"http_request_raw templating failed, missing key: {exc}")

    from pyrit.prompt_target import HTTPTargetX, MultiFieldResponseParser, OpenAIChatTarget

    multi_parser = MultiFieldResponseParser(field_definitions=field_defs)
    tid_parser = build_thread_id_parser(thread_id_pattern)

    timeout = aiohttp.ClientTimeout(
        total=timeout_seconds,
        connect=timeout_seconds,
        sock_connect=timeout_seconds,
        sock_read=timeout_seconds,
    )
    session = aiohttp.ClientSession(timeout=timeout)

    http_target = HTTPTargetX(
        http_request=http_request_templated,
        prompt_regex_string="{PROMPT}",
        use_tls=True,
        response_parser=multi_parser,
        thread_id_parser=tid_parser,
        client=session,
    )

    thread_id_injector_fn = lambda raw, tid, key=thread_id_key: inject_thread_id(raw, tid, key)

    from pyrit.executor.attack import (
        AttackAdversarialConfig,
        AttackConverterConfig,
        AttackScoringConfig,
        RedTeamingAttack,
    )
    from pyrit.prompt_normalizer import PromptNormalizer
    from pyrit.common import get_conversation_report_async, create_report

    scorer_weight_map: Dict[str, float] = {}
    scorer_required_map: Dict[str, bool] = {}
    for spec in evaluator_specs:
        if spec.get("weight") is not None:
            scorer_weight_map[spec["identifier_json"]] = float(spec["weight"])
        if spec.get("required") is not None:
            scorer_required_map[spec["identifier_json"]] = bool(spec["required"])

    reports: List[Dict[str, Any]] = []
    start_time = time.time()

    try:
        for objective in objectives:
            evaluator_variables = {"objective": objective}
            per_objective_scorers = instantiate_per_objective_scorers(
                evaluator_specs,
                additional_variables=evaluator_variables,
            )
            objective_scorer = per_objective_scorers[0]
            auxiliary_scorers = per_objective_scorers[1:]

            attack_scoring_config = AttackScoringConfig(
                objective_scorer=objective_scorer,
                auxiliary_scorers=auxiliary_scorers,
                use_score_as_feedback=use_score_as_feedback,
                successful_objective_threshold=successful_objective_threshold,
            )
            attack_adversarial_config = AttackAdversarialConfig(
                target=OpenAIChatTarget(),
                system_prompt_path=strategy_path,
                seed_prompt=seed_prompt,
            )
            attack_converter_config = AttackConverterConfig(
                request_converters=[],
                response_converters=[],
            )

            attack = RedTeamingAttack(
                objective_target=http_target,
                attack_adversarial_config=attack_adversarial_config,
                attack_converter_config=attack_converter_config,
                attack_scoring_config=attack_scoring_config,
                prompt_normalizer=PromptNormalizer(),
                evaluate_chat=evaluate_chat,
                include_history=include_history,
                scorer_type=scorer_type,
                thread_id_injector=thread_id_injector_fn,
                max_retries=max_retries,
                max_turns=max_turns,
            )

            attack_result = await attack.execute_async(objective=objective)
            reports.append(await get_conversation_report_async(attack_result))
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return _fail(f"Network error/timeout while contacting target: {exc}")
    finally:
        await session.close()

    elapsed = time.time() - start_time

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = out_dir / "simulation_report.html"
    create_report(
        results=reports,
        threshold=report_threshold,
        execution_time=elapsed,
        description=(
            "Multi-turn simulation results. Each conversation reflects an objective-driven attack "
            "attempt orchestrated by an adversarial agent."
        ),
        save_path=report_path,
        scorer_weights=scorer_weight_map,
        scorer_required=scorer_required_map,
        pass_on_any_success=True,
        report_metadata=report_metadata,
    )

    json_report_path = out_dir / "simulation_report.json"
    report_payload = {
        "report_threshold": report_threshold,
        "execution_time_seconds": elapsed,
        "output_directory": str(out_dir),
        "report_html": str(report_path),
        "objectives": objectives,
        "scorer_weights": scorer_weight_map,
        "scorer_required": scorer_required_map,
        "evaluators": [
            {
                "identifier": spec["instance"].get_identifier(),
                "display_path": spec.get("display_path"),
                "weight": spec.get("weight"),
                "required": spec.get("required"),
            }
            for spec in evaluator_specs
        ],
        "chat_reports": reports,
        "strategy_path": str(strategy_path),
        "max_turns": max_turns,
        "use_score_as_feedback": use_score_as_feedback,
        "scorer_type": scorer_type,
    }
    if report_metadata is not None:
        report_payload["report_metadata"] = report_metadata

    serialized_report = json.dumps(report_payload, default=_json_default, indent=2)
    json_report_path.write_text(serialized_report, encoding="utf-8")
    normalized_report_payload = json.loads(serialized_report)

    for spec in evaluator_specs:
        completion_hook = getattr(spec["instance"], "on_run_complete", None)
        if callable(completion_hook):
            try:
                await _invoke_completion_hook(
                    completion_hook,
                    report_payload=normalized_report_payload,
                    report_path=json_report_path,
                )
            except Exception as exc:  # pragma: no cover
                logging.error(
                    "Error running on_run_complete for evaluator '%s': %s",
                    spec.get("display_path", spec["instance"].__class__.__name__),
                    exc,
                )

    print(f"Reports: {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyrit-sim",
        description="Run PyRIT multi-turn simulations using objectives from the config",
    )
    parser.add_argument("--config", required=True, help="Path to simulation YAML config")
    parser.add_argument("--scorer", required=True, help="JSON object describing objective and auxiliary scorers")
    parser.add_argument("--strategy-path", required=False, help="Override strategy YAML path (defaults to config value)")
    parser.add_argument("--out", required=True, default="pyrit_reports", help="Output directory")
    parser.add_argument("--target-endpoint", required=True, help="API base URL (overrides TARGET_ENDPOINT)")
    parser.add_argument("--auth-token", required=True, help="Authentication token (overrides AUTH_TOKEN)")
    parser.add_argument("--openai-api-key", required=True, help="OpenAI API key (overrides OPENAI_API_KEY)")
    parser.add_argument("--openai-chat-endpoint", required=True, help="OpenAI chat endpoint (overrides OPENAI_CHAT_ENDPOINT)")
    parser.add_argument("--openai-chat-model", required=False, help="OpenAI chat model (overrides OPENAI_CHAT_MODEL)")
    parser.add_argument(
        "--report-metadata",
        required=False,
        help="Optional JSON object to display under the report title",
    )
    parser.add_argument(
        "--scorer-temperature",
        required=False,
        type=float,
        help="Temperature to use for LLM-based scorers (passed to OpenAIChatTarget); defaults to model default",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    code = asyncio.run(run_simulation_async(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
