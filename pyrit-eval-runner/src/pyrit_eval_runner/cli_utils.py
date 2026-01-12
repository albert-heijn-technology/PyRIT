from __future__ import annotations

import inspect
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _fail(msg: str) -> int:
    logging.error(msg)
    sys.exit(2)


def _resolve_required_setting(arg_value: Optional[str], env_name: str) -> str:
    if arg_value:
        os.environ[env_name] = arg_value
        return arg_value

    val = os.getenv(env_name)
    if val:
        return val

    _fail(f"Missing required setting '{env_name}'. Provide it via CLI or environment variable.")
    raise AssertionError("unreachable")


def _resolve_optional_setting(
    arg_value: Optional[str], env_name: str, default: Optional[str] = None
) -> Optional[str]:
    if arg_value:
        os.environ[env_name] = arg_value
        return arg_value

    val = os.getenv(env_name)
    if val is not None:
        return val

    if default is not None:
        os.environ[env_name] = default
    return default


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


def _collect_evaluator_paths(scorer_raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    main_normalized = _normalise_evaluator_entry(scorer_raw.get("main"))
    print("Normalized main scorer entry:", main_normalized)
    auxiliaries_raw = scorer_raw.get("auxiliary", [])
    if not isinstance(auxiliaries_raw, list):
        raise ValueError("evaluator_paths auxiliary entry must be a list")
    auxiliaries_normalized = [_normalise_evaluator_entry(entry) for entry in auxiliaries_raw]
    print("Normalized auxiliary scorer entries:", auxiliaries_normalized)
    return [main_normalized] + auxiliaries_normalized


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


def build_thread_id_parser(thread_id_pattern: str | None):
    if not thread_id_pattern:
        return None

    s = rf"{re.escape(thread_id_pattern)}\s*\n\s*data:(.*)"

    def parse(response: Any) -> Optional[str]:
        if not isinstance(response, str):
            response = str(response)
        m = re.search(s, response)
        return m.group(1).strip() if m else None

    return parse


def inject_thread_id(raw_http_request: str, thread_id: str, key: str = "") -> str:
    if thread_id != "" and key != "":
        url_pattern = r"(https?://[^\s]+)"
        m = re.search(url_pattern, raw_http_request)
        if not m:
            raise ValueError("No URL found in raw HTTP request; cannot inject thread ID.")

        original_url = m.group(1)
        replaced = re.sub(rf"([?&]){re.escape(key)}=[^&]*", "", original_url)
        sep = "&" if "?" in replaced else "?"
        new_url = f"{replaced}{sep}{key}={thread_id}"
        return raw_http_request.replace(original_url, new_url)
    return raw_http_request


__all__ = [
    "_setup_logging",
    "_fail",
    "_resolve_required_setting",
    "_resolve_optional_setting",
    "_split_path_list",
    "_collect_evaluator_paths",
    "_load_yaml",
    "_json_default",
    "_invoke_completion_hook",
    "build_thread_id_parser",
    "inject_thread_id",
]
