import argparse
import asyncio
import importlib.util
import inspect
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Mapping
from pyrit.prompt_target import HTTPTargetX
import aiohttp
import yaml


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _fail(msg: str) -> None:
    logging.error(msg)
    sys.exit(2)


def _resolve_required_setting(arg_value: Optional[str], env_name: str) -> str:
    """Return a required configuration value preferring CLI arg over env."""
    if arg_value:
        os.environ[env_name] = arg_value
        return arg_value

    val = os.getenv(env_name)
    if not val:
        _fail(f"Missing configuration for {env_name}")
    return val


def _resolve_optional_setting(
    arg_value: Optional[str], env_name: str, default: Optional[str] = None
) -> Optional[str]:
    """Return an optional configuration value preferring CLI arg, then env, then default."""
    if arg_value:
        os.environ[env_name] = arg_value
        return arg_value

    val = os.getenv(env_name)
    if val is not None:
        return val

    if default is not None:
        os.environ[env_name] = default
    return default


def _resolve_path(base_dir: Path, value: Optional[str]) -> Optional[Path]:
    if value is None:
        return None
    p = Path(value)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p


def _split_path_list(value: str) -> List[str]:
    return [item.strip() for item in value.split(os.pathsep) if item.strip()]


def _normalise_evaluator_entry(entry: Any) -> Dict[str, Any]:
    if isinstance(entry, str):
        return {"path": entry}
    if isinstance(entry, Mapping):
        if "path" not in entry:
            raise ValueError("Each evaluator entry must include a 'path' key")
        normalised: Dict[str, Any] = {"path": str(entry["path"])}
        if "weight" in entry and entry["weight"] is not None:
            try:
                normalised["weight"] = float(entry["weight"])
            except (TypeError, ValueError):
                raise ValueError("Evaluator weight must be a numeric value")
        if "required" in entry and entry["required"] is not None:
            normalised["required"] = bool(entry["required"])
        if "callable" in entry and entry["callable"] is not None:
            normalised["callable"] = str(entry["callable"])
        if "params" in entry and entry["params"] is not None:
            params = entry["params"]
            if not isinstance(params, Mapping):
                raise ValueError("Evaluator params must be a mapping")
            normalised["params"] = dict(params)
        return normalised
    raise ValueError("Evaluator entries must be strings or mappings containing a 'path'")


def _collect_evaluator_paths(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    env_multi = os.getenv("PYRIT_EVALUATOR_PATHS")
    if env_multi:
        parts = _split_path_list(env_multi)
        if parts:
            return [{"path": part} for part in parts]
        raise ValueError("PYRIT_EVALUATOR_PATHS is set but empty")

    env_single = os.getenv("PYRIT_EVALUATOR_PATH")
    if env_single:
        return [{"path": env_single}]

    cfg_multi = cfg.get("evaluator_paths")
    if cfg_multi is not None:
        if not isinstance(cfg_multi, list):
            raise ValueError("Config key 'evaluator_paths' must be a list")
        entries = [_normalise_evaluator_entry(item) for item in cfg_multi]
        if not entries:
            raise ValueError("Config key 'evaluator_paths' must contain at least one entry")
        return entries

    cfg_single = cfg.get("evaluator_path")
    if cfg_single:
        return [_normalise_evaluator_entry(cfg_single)]

    return []


def _load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, Path)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, set):
        return sorted(value)
    return str(value)


async def _invoke_completion_hook(
    hook: Any,
    *,
    report_payload: Dict[str, Any],
    report_path: Path,
) -> None:
    try:
        signature = inspect.signature(hook)
    except (TypeError, ValueError):
        signature = None

    kwargs: Dict[str, Any] = {}
    if signature is not None:
        parameters = signature.parameters
        accepts_var_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()
        )
        if accepts_var_kwargs:
            kwargs = {"report_payload": report_payload, "report_path": str(report_path)}
        else:
            if "report_payload" in parameters:
                kwargs["report_payload"] = report_payload
            if "report_path" in parameters:
                kwargs["report_path"] = str(report_path)

    result = hook(**kwargs)
    if inspect.isawaitable(result):
        await result

# --- Thread helpers (regex based) ---
def build_thread_id_parser(thread_id_pattern: str):
    # Find the event line; then extract payload from next data: line
    s = rf"{re.escape(thread_id_pattern)}\s*\n\s*data:(.*)"

    def parse(response: Any) -> Optional[str]:
        if not isinstance(response, str):
            response = str(response)
        m = re.search(s, response)
        return m.group(1).strip() if m else None

    return parse


def inject_thread_id(raw_http_request: str, thread_id: str, key: str = "threadId") -> str:
    # Replace or add query parameter in the first URL
    url_pattern = r"(https?://[^\s]+)"
    m = re.search(url_pattern, raw_http_request)
    if not m:
        raise ValueError("No URL found in raw HTTP request; cannot inject thread ID.")

    original_url = m.group(1)
    # Remove existing key if present
    replaced = re.sub(rf"([?&]){re.escape(key)}=[^&]*", "", original_url)
    sep = "&" if "?" in replaced else "?"
    new_url = f"{replaced}{sep}{key}={thread_id}"
    return raw_http_request.replace(original_url, new_url)

async def run_async(args: argparse.Namespace) -> int:
    _setup_logging()

    # Env requirements for HTTP templating
    base_url = _resolve_required_setting(args.target_endpoint, "TARGET_ENDPOINT")
    token = _resolve_required_setting(args.auth_token, "AUTH_TOKEN")

    api_key = _resolve_required_setting(args.openai_api_key, "OPENAI_API_KEY")
    chat_endpoint = _resolve_optional_setting(
        args.openai_chat_endpoint, "OPENAI_CHAT_ENDPOINT", "https://api.openai.com/v1"
    )
    chat_model = _resolve_optional_setting(
        args.openai_chat_model, "OPENAI_CHAT_MODEL", "gpt-4o-mini"
    )

    if args.openai_api_key or "OPENAI_CHAT_KEY" not in os.environ:
        os.environ["OPENAI_CHAT_KEY"] = api_key
    if chat_endpoint:
        os.environ["OPENAI_CHAT_ENDPOINT"] = chat_endpoint
    if chat_model:
        os.environ["OPENAI_CHAT_MODEL"] = chat_model

    cfg_path = Path(args.config).resolve()
    if not cfg_path.exists():
        _fail(f"Config not found: {cfg_path}")
    cfg_dir = cfg_path.parent
    cfg = _load_yaml(cfg_path)

    # Resolve paths with overrides (flag > env > yaml)
    dataset_path = os.getenv("PYRIT_DATASET_PATH") or cfg.get("dataset_path")
    if not dataset_path:
        _fail("Config must include dataset_path (or override via flags/env)")

    try:
        evaluator_paths = _collect_evaluator_paths(cfg)
    except ValueError as exc:
        _fail(str(exc))

    if not evaluator_paths:
        _fail("Config must include evaluator_paths (or override via env)")

    dataset_path_p = _resolve_path(cfg_dir, dataset_path)
    if not dataset_path_p or not dataset_path_p.exists():
        _fail(f"Dataset file not found: {dataset_path_p}")

    evaluator_entries: List[Dict[str, Any]] = []
    seen_evaluators: Dict[Any, str] = {}
    for entry in evaluator_paths:
        raw_path = entry.get("path")
        resolved_path = _resolve_path(cfg_dir, raw_path)
        if not resolved_path or not resolved_path.exists():
            _fail(f"Evaluator file not found: {resolved_path}")

        canonical = resolved_path.resolve()
        suffix = canonical.suffix.lower()
        callable_name = entry.get("callable")
        params = entry.get("params") or {}
        if suffix == ".py" and not callable_name:
            _fail(
                "Programmatic evaluator entries referencing '.py' files must include a 'callable' name"
            )
        if suffix not in (".yaml", ".yml", ".py"):
            _fail(
                "Evaluator path must end with .yaml/.yml for LLM scorers or .py for programmatic scorers"
            )
        duplicate_key: Any = (canonical, callable_name) if suffix == ".py" else canonical
        if duplicate_key in seen_evaluators:
            _fail(
                "Duplicate evaluator paths detected: "
                f"'{raw_path}' resolves to the same location as "
                f"'{seen_evaluators[duplicate_key]}'"
            )

        if suffix == ".py" and params and not isinstance(params, dict):
            _fail("Evaluator params must be provided as a mapping")

        seen_evaluators[duplicate_key] = str(raw_path)
        evaluator_entries.append(
            {
                "resolved_path": resolved_path,
                "display_path": str(raw_path),
                "weight": entry.get("weight"),
                "required": bool(entry.get("required", False)),
                "callable": callable_name,
                "params": params if isinstance(params, dict) else {},
                "kind": "programmatic" if suffix == ".py" else "llm",
            }
        )

    http_raw = cfg.get("http_request_raw")
    field_defs = cfg.get("field_defs")
    thread_id_pattern = cfg.get("thread_id_pattern")
    thread_id_key = cfg.get("thread_id_query_param_key", "threadId")

    env_report_threshold = os.getenv("PYRIT_REPORT_THRESHOLD")
    if env_report_threshold is not None:
        report_threshold = float(env_report_threshold)
    elif "report_threshold" in cfg:
        report_threshold = float(cfg["report_threshold"])
    else:
        report_threshold = 0.8
    if not isinstance(field_defs, list):
        _fail("Config field_defs must be a list")
    if not http_raw or not thread_id_pattern:
        _fail("Config must include http_request_raw and thread_id_pattern")

    # Template the raw HTTP request with endpoint + token; preserve {PROMPT}
    try:
        http_request_templated = str(http_raw).format(base_url=base_url, token=token)
    except KeyError as e:
        _fail(f"http_request_raw templating failed, missing key: {e}")

    # Initialize PyRIT in-memory DB
    from pyrit.common import initialize_pyrit, IN_MEMORY
    initialize_pyrit(memory_db_type=IN_MEMORY)

    # Build parser and helpers
    from pyrit.prompt_target import MultiFieldResponseParser

    multi_parser = MultiFieldResponseParser(field_definitions=field_defs)
    tid_parser = build_thread_id_parser(thread_id_pattern)

    # Networking client
    timeout = aiohttp.ClientTimeout(connect=60, sock_connect=60, sock_read=300)
    session = aiohttp.ClientSession(timeout=timeout)

    # Targets and scorer
    http_target = HTTPTargetX(
        http_request=http_request_templated,
        prompt_regex_string="{PROMPT}",
        use_tls=True,
        response_parser=multi_parser,
        thread_id_parser=tid_parser,
        client=session,
    )

    scorer_type = os.getenv("PYRIT_SCORER_TYPE", "float_scale").strip().lower()
    if scorer_type not in ("float_scale", "true_false"):
        _fail("PYRIT_SCORER_TYPE must be 'float_scale' or 'true_false'")

    from pyrit.prompt_target import OpenAIChatTarget
    from pyrit.score import Evaluator, Scorer

    evaluator_specs: List[Dict[str, Any]] = []
    for entry in evaluator_entries:
        if entry["kind"] == "llm":
            scorer_instance: Scorer = Evaluator(
                chat_target=OpenAIChatTarget(),
                evaluator_yaml_path=entry["resolved_path"],
                scorer_type=scorer_type,  # type: ignore[arg-type]
            )
        else:
            module_name = f"_pyrit_eval_runner_dynamic_{len(evaluator_specs)}"
            spec = importlib.util.spec_from_file_location(module_name, entry["resolved_path"])
            if spec is None or spec.loader is None:
                _fail(f"Failed to load programmatic scorer module: {entry['display_path']}")
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                _fail(f"Error importing programmatic scorer '{entry['display_path']}': {exc}")

            try:
                factory = getattr(module, entry["callable"])
            except AttributeError:
                _fail(
                    "Programmatic evaluator callable '{callable_name}' not found in '{path}'".format(
                        callable_name=entry["callable"], path=entry["display_path"]
                    )
                )

            if not callable(factory):
                _fail(
                    "Programmatic evaluator callable '{callable_name}' in '{path}' is not callable".format(
                        callable_name=entry["callable"], path=entry["display_path"]
                    )
                )

            params = entry.get("params") or {}
            try:
                scorer_instance = factory(**params)
            except Exception as exc:
                _fail(
                    "Failed to instantiate programmatic evaluator '{callable_name}' from '{path}': {error}".format(
                        callable_name=entry["callable"], path=entry["display_path"], error=exc
                    )
                )

            if not isinstance(scorer_instance, Scorer):
                _fail(
                    "Programmatic evaluator '{callable_name}' in '{path}' must return an instance of pyrit.score.Scorer".format(
                        callable_name=entry["callable"], path=entry["display_path"]
                    )
                )

        original_get_identifier = scorer_instance.get_identifier

        def _identifier_with_path(self, _orig=original_get_identifier, _path=entry["display_path"]):
            identifier = _orig()
            identifier["config_path"] = _path
            return identifier

        scorer_instance.get_identifier = _identifier_with_path.__get__(
            scorer_instance, scorer_instance.__class__
        )  # type: ignore[attr-defined]

        if entry.get("weight") is not None:
            setattr(scorer_instance, "_report_weight", float(entry["weight"]))

        evaluator_specs.append({**entry, "instance": scorer_instance})

    objective_evaluator = evaluator_specs[0]["instance"]
    auxiliary_evaluators = [spec["instance"] for spec in evaluator_specs[1:]]

    from pyrit.executor.attack import (
        PromptSendingAttack,
        AttackConverterConfig,
        AttackScoringConfig,
    )

    attack = PromptSendingAttack(
        objective_target=http_target,
        attack_converter_config=AttackConverterConfig(request_converters=[], response_converters=[]),
        attack_scoring_config=AttackScoringConfig(
            objective_scorer=objective_evaluator,
            auxiliary_scorers=auxiliary_evaluators,
        ),
        max_attempts_on_failure=0,
    )

    scorer_weight_map: Dict[str, float] = {}
    scorer_required_map: Dict[str, bool] = {}
    for spec in evaluator_specs:
        identifier_json = json.dumps(spec["instance"].get_identifier(), sort_keys=True)
        if spec.get("weight") is not None:
            scorer_weight_map[identifier_json] = float(spec["weight"])
        if spec.get("required") is not None:
            scorer_required_map[identifier_json] = bool(spec["required"])

    # Load dataset (compatible with Repo A's loader semantics)
    def _load_test_data(file_path: Path) -> List[Dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            raise ValueError("Dataset YAML should be a list of entries")
        qa_pairs_local: List[Dict[str, Any]] = []
        for entry in data:
            test_case_id = entry.get("test_case_id")

            if "conversation" in entry:
                qa_entry = dict(entry)
                if test_case_id is not None:
                    qa_entry["test_case_id"] = test_case_id
                qa_pairs_local.append(qa_entry)
            elif "question" in entry and ("expected_outcome" in entry or "expected_outcomes" in entry):
                qa_entry = {
                    "question": entry["question"],
                    "expected_outcome": entry.get("expected_outcome", entry.get("expected_outcomes")),
                }
                if test_case_id is not None:
                    qa_entry["test_case_id"] = test_case_id
                qa_pairs_local.append(qa_entry)
            else:
                raise ValueError(f"Unknown test case format in entry: {entry}")
        return qa_pairs_local

    qa_pairs = _load_test_data(dataset_path_p)

    # No sharding/max-examples: run all dataset examples

    # Execute
    start = time.time()
    try:
        results = await attack.perform_dataset_attack(
            qa_pairs,
            thread_id_injector=lambda r, tid: inject_thread_id(r, tid, thread_id_key),
        )
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        await session.close()
        _fail(f"Network error/timeout while contacting target: {e}")
    finally:
        await session.close()

    # Collect conversation reports
    from pyrit.common import get_conversation_report_async, create_report
    chat_reports: List[Dict[str, Any]] = []
    for ar in results:
        rep = await get_conversation_report_async(ar)
        chat_reports.append(rep)
    elapsed = time.time() - start

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # HTML report (timestamped inside helper)
    create_report(
        results=chat_reports,
        threshold=report_threshold,
        execution_time=elapsed,
        description=(
            "Evaluation of dataset examples. Final conversation score is the minimum weighted step score across the transcript."
        ),
        save_path=out_dir / "dataset_report.html",
        scorer_weights=scorer_weight_map,
        scorer_required=scorer_required_map,
    )

    json_report_path = out_dir / "dataset_report.json"
    report_payload = {
        "report_threshold": report_threshold,
        "execution_time_seconds": elapsed,
        "dataset_path": str(dataset_path_p) if dataset_path_p else None,
        "output_directory": str(out_dir),
        "report_html": str(out_dir / "dataset_report.html"),
        "scorer_weights": scorer_weight_map,
        "scorer_required": scorer_required_map,
        "raw_result_count": len(results),
        "evaluators": [
            {
                "identifier": spec["instance"].get_identifier(),
                "display_path": spec.get("display_path"),
                "weight": spec.get("weight"),
                "required": spec.get("required"),
            }
            for spec in evaluator_specs
        ],
        "chat_reports": chat_reports,
    }

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
            except Exception as exc:  # pragma: no cover - defensive logging only
                logging.error(
                    "Error running on_run_complete for evaluator '%s': %s",
                    spec.get("display_path", spec["instance"].__class__.__name__),
                    exc,
                )

    # Only print the reports directory; no gating/exit failure
    print(f"Reports: {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pyrit-eval", description="Run PyRIT evaluations from a YAML config")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run evaluations", description="Run evaluations")
    run.add_argument("--config", required=True, help="Path to Repo-B YAML config")
    run.add_argument("--out", default="pyrit_reports", help="Output directory")
    run.add_argument(
        "--target-endpoint",
        help="API base URL (overrides TARGET_ENDPOINT)",
    )
    run.add_argument(
        "--auth-token",
        help="Authentication token (overrides AUTH_TOKEN)",
    )
    run.add_argument(
        "--openai-api-key",
        help="OpenAI API key (overrides OPENAI_API_KEY)",
    )
    run.add_argument(
        "--openai-chat-endpoint",
        help="OpenAI chat endpoint (overrides OPENAI_CHAT_ENDPOINT)",
    )
    run.add_argument(
        "--openai-chat-model",
        help="OpenAI chat model (overrides OPENAI_CHAT_MODEL)",
    )

    return p


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        code = asyncio.run(run_async(args))
        sys.exit(code)
    else:
        parser.print_help()
