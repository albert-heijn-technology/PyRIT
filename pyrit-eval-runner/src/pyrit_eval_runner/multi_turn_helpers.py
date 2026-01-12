from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pyrit.score import Scorer


def configure_openai_settings(args) -> None:
    if getattr(args, "openai_api_key", None) or "OPENAI_CHAT_KEY" not in os.environ:
        os.environ["OPENAI_CHAT_KEY"] = args.openai_api_key
    if getattr(args, "openai_chat_endpoint", None):
        os.environ["OPENAI_CHAT_ENDPOINT"] = args.openai_chat_endpoint
    if getattr(args, "openai_chat_model", None):
        os.environ["OPENAI_CHAT_MODEL"] = args.openai_chat_model or os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")


def prepare_evaluator_specs(
    evaluator_paths: List[Dict[str, Any]],
    *,
    scorer_type: str,
    openai_chat_target_kwargs: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    seen_paths: Dict[Any, str] = {}

    from pyrit.prompt_target import OpenAIChatTarget
    from pyrit.score import Evaluator, Scorer

    for index, entry in enumerate(evaluator_paths):
        raw_path = entry.get("path")
        resolved_path = Path(raw_path)
        if not resolved_path or not resolved_path.exists():
            raise ValueError(f"Evaluator file not found: {resolved_path}")

        canonical = resolved_path.resolve()
        suffix = canonical.suffix.lower()
        callable_name = entry.get("callable")
        params = entry.get("params") or {}
        if suffix == ".py" and not callable_name:
            raise ValueError(
                "Programmatic evaluator entries referencing '.py' files must include a 'callable' name"
            )
        if suffix not in (".yaml", ".yml", ".py"):
            raise ValueError(
                "Evaluator path must end with .yaml/.yml for LLM scorers or .py for programmatic scorers"
            )

        duplicate_key: Any = (canonical, callable_name) if suffix == ".py" else canonical
        if duplicate_key in seen_paths:
            raise ValueError(
                "Duplicate evaluator paths detected: "
                f"'{raw_path}' resolves to the same location as "
                f"'{seen_paths[duplicate_key]}'"
            )
        seen_paths[duplicate_key] = str(raw_path)

        if suffix == ".py" and params and not isinstance(params, dict):
            raise ValueError("Evaluator params must be provided as a mapping")

        target_kwargs = dict(openai_chat_target_kwargs or {})

        if suffix == ".py":
            module_name = f"_pyrit_multi_turn_dynamic_{index}"
            spec = importlib.util.spec_from_file_location(module_name, resolved_path)
            if spec is None or spec.loader is None:
                raise ValueError(f"Failed to load programmatic scorer module: {raw_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            try:
                factory = getattr(module, callable_name)
            except AttributeError as exc:
                raise ValueError(
                    f"Programmatic evaluator callable '{callable_name}' not found in '{raw_path}'"
                ) from exc

            if not callable(factory):
                raise ValueError(
                    f"Programmatic evaluator callable '{callable_name}' in '{raw_path}' is not callable"
                )

            params_dict = params if isinstance(params, dict) else {}

            def _programmatic_loader(
                additional_evaluator_variables: Optional[Dict[str, Any]] = None,
                _factory=factory,
                _params=params_dict,
                _callable=callable_name,
                _display=str(raw_path),
            ) -> Scorer:
                instance = _factory(**_params)
                if not isinstance(instance, Scorer):
                    raise ValueError(
                        f"Programmatic evaluator '{_callable}' in '{_display}' must return an instance of pyrit.score.Scorer"
                    )
                return instance

            loader = _programmatic_loader
        else:

            def _llm_loader(
                additional_evaluator_variables: Optional[Dict[str, Any]] = None,
                _path=resolved_path,
                _scorer_type=scorer_type,
                _target_kwargs=target_kwargs,
            ) -> Scorer:
                return Evaluator(
                    chat_target=OpenAIChatTarget(**_target_kwargs),
                    evaluator_yaml_path=_path,
                    scorer_type=_scorer_type,  # type: ignore[arg-type]
                    additional_evaluator_variables=additional_evaluator_variables,
                )

            loader = _llm_loader

        instance = loader(None)
        if entry.get("weight") is not None:
            setattr(instance, "_report_weight", float(entry["weight"]))

        spec_entry = {
            "resolved_path": resolved_path,
            "display_path": str(raw_path),
            "weight": entry.get("weight"),
            "required": bool(entry.get("required", False)),
            "callable": callable_name,
            "params": params if isinstance(params, dict) else {},
            "kind": "programmatic" if suffix == ".py" else "llm",
            "loader": loader,
            "instance": instance,
            "identifier_json": json.dumps(instance.get_identifier(), sort_keys=True),
        }
        specs.append(spec_entry)

    return specs


def instantiate_per_objective_scorers(
    evaluator_specs: List[Dict[str, Any]],
    *,
    additional_variables: Dict[str, Any],
) -> List["Scorer"]:
    from pyrit.score import Scorer

    scorers: List[Scorer] = []
    for spec in evaluator_specs:
        variables = additional_variables if spec["kind"] == "llm" else None
        instance = spec["loader"](variables)
        if spec.get("weight") is not None:
            setattr(instance, "_report_weight", float(spec["weight"]))
        scorers.append(instance)
    return scorers
