# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Any, Iterable, List, Dict, Union

from pyrit.common.text_helper import generate_simulation_report, generate_dataset_report


async def get_conversation_report_async(attack_result: Any) -> dict:
    """
    Minimal shim to build conversation reports without accessing memory internals.

    Delegates to OrchestratorResult.get_conversation_report_async(), which
    assembles the transcript and includes scores/rationales per assistant turn.

    This keeps report generation backend-agnostic and avoids UUID/SQLite issues.
    """
    # The "attack_result" is expected to be an instance of OrchestratorResult
    # or a compatible object exposing get_conversation_report_async().
    return await attack_result.get_conversation_report_async()


async def collect_conversation_reports_async(
        attack_results: Iterable[Any],
) -> List[Dict[str, Union[str, float, dict, list]]]:
    """
    Gathers per-conversation reports for a collection of orchestrator results.

    Args:
        attack_results: Iterable of OrchestratorResult-like objects.

    Returns:
        List of conversation report dicts suitable for HTML generation.
    """
    reports: List[Dict[str, Union[str, float, dict, list]]] = []
    for ar in attack_results:
        reports.append(await get_conversation_report_async(ar))
    return reports


def create_report(
        *,
        results: list,
        execution_time: float = 0.0,
        description: str = "",
        title: str = "Comprehensive Simulation Report",
        save_path: str = "simulation_report.html",
        threshold: float = 0.8,
        is_dataset: bool = False,
) -> None:
    """
    Writes an HTML report from conversation or dataset results using the built-in generators.

    For chat evaluations, uses generate_simulation_report. For dataset-style tabular
    rendering (single user/assistant row per case), set is_dataset=True to use
    generate_dataset_report.
    """
    if is_dataset:
        generate_dataset_report(
            results=results,
            threshold=threshold,
            title=title,
            description=description,
            execution_time=execution_time,
            save_path=save_path,
        )
    else:
        generate_simulation_report(
            results=results,
            threshold=threshold,
            title=title,
            description=description,
            execution_time=execution_time,
            save_path=save_path,
        )

