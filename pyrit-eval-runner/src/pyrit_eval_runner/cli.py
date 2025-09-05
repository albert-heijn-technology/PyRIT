import argparse
import asyncio
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from pyrit.prompt_target import HTTPTargetX
import aiohttp
import yaml


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _fail(msg: str) -> None:
    logging.error(msg)
    sys.exit(2)


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        _fail(f"Missing environment variable: {name}")
    return val


def _resolve_path(base_dir: Path, value: Optional[str]) -> Optional[Path]:
    if value is None:
        return None
    p = Path(value)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p


def _load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

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
    base_url = _require_env("TARGET_ENDPOINT")
    token = _require_env("AUTH_TOKEN")

    # Map OPENAI_API_KEY -> OPENAI_CHAT_KEY if provided
    api_key = _require_env("OPENAI_API_KEY")
    os.environ.setdefault("OPENAI_CHAT_KEY", api_key)
    os.environ.setdefault("OPENAI_CHAT_ENDPOINT", os.getenv("OPENAI_CHAT_ENDPOINT", "https://api.openai.com/v1"))
    os.environ.setdefault("OPENAI_CHAT_MODEL", os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"))

    cfg_path = Path(args.config).resolve()
    if not cfg_path.exists():
        _fail(f"Config not found: {cfg_path}")
    cfg_dir = cfg_path.parent
    cfg = _load_yaml(cfg_path)

    # Resolve paths with overrides (flag > env > yaml)
    dataset_path = os.getenv("PYRIT_DATASET_PATH") or cfg.get("dataset_path")
    evaluator_path = os.getenv("PYRIT_EVALUATOR_PATH") or cfg.get("evaluator_path")
    if not dataset_path or not evaluator_path:
        _fail("Config must include dataset_path and evaluator_path (or override via flags/env)")

    dataset_path_p = _resolve_path(cfg_dir, dataset_path)
    evaluator_path_p = _resolve_path(cfg_dir, evaluator_path)
    if not dataset_path_p or not dataset_path_p.exists():
        _fail(f"Dataset file not found: {dataset_path_p}")
    if not evaluator_path_p or not evaluator_path_p.exists():
        _fail(f"Evaluator file not found: {evaluator_path_p}")

    http_raw = cfg.get("http_request_raw")
    field_defs = cfg.get("field_defs")
    thread_id_pattern = cfg.get("thread_id_pattern")
    thread_id_key = cfg.get("thread_id_query_param_key", "threadId")
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
    from pyrit.score import Evaluator
    evaluator = Evaluator(
        chat_target=OpenAIChatTarget(),
        evaluator_yaml_path=evaluator_path_p,
        scorer_type=scorer_type,  # type: ignore[arg-type]
    )

    from pyrit.executor.attack import (
        PromptSendingAttack,
        AttackConverterConfig,
        AttackScoringConfig,
    )

    attack = PromptSendingAttack(
        objective_target=http_target,
        attack_converter_config=AttackConverterConfig(request_converters=[], response_converters=[]),
        attack_scoring_config=AttackScoringConfig(objective_scorer=evaluator, auxiliary_scorers=[]),
        max_attempts_on_failure=0,
    )

    # Load dataset (compatible with Repo A's loader semantics)
    def _load_test_data(file_path: Path) -> List[Dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            raise ValueError("Dataset YAML should be a list of entries")
        qa_pairs_local: List[Dict[str, Any]] = []
        for entry in data:
            if "conversation" in entry:
                qa_pairs_local.append(entry)
            elif "question" in entry and ("expected_outcome" in entry or "expected_outcomes" in entry):
                qa_pairs_local.append({
                    "question": entry["question"],
                    "expected_outcome": entry.get("expected_outcome", entry.get("expected_outcomes"))
                })
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
        execution_time=elapsed,
        description=(
            "Evaluation of dataset examples. Final conversation score is the minimum step score across the transcript."
        ),
        save_path=out_dir / "dataset_report.html",
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

    return p


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        code = asyncio.run(run_async(args))
        sys.exit(code)
    else:
        parser.print_help()
