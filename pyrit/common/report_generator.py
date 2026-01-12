# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import html as html_lib
import json
import re
from pyrit.memory import CentralMemory

# ------------------------
# Utility functions
# ------------------------

def sanitize(text: str) -> str:
    """Sanitize text for HTML display (except for trusted HTML snippets)."""
    return str(text).replace("<", "&lt;").replace(">", "&gt;")

def linkify(text: str) -> str:
    """Convert URLs in plain text into safe clickable links."""
    if text is None:
        return ""

    pattern = re.compile(r"(https?://[^\s<]+)")
    parts = pattern.split(str(text))
    html_parts: List[str] = []
    trailing_punct = ".,);:!?]"

    for part in parts:
        if not part:
            continue
        if pattern.fullmatch(part):
            url = part
            suffix = ""
            while url and url[-1] in trailing_punct:
                suffix = url[-1] + suffix
                url = url[:-1]
            if url:
                escaped_href = html_lib.escape(url, quote=True)
                escaped_text = html_lib.escape(url)
                html_parts.append(
                    f"<a href='{escaped_href}' target='_blank' rel='noopener noreferrer'>{escaped_text}</a>"
                )
                if suffix:
                    html_parts.append(html_lib.escape(suffix))
            else:
                html_parts.append(html_lib.escape(part))
        else:
            html_parts.append(html_lib.escape(part))
    return "".join(html_parts)


def render_expandable_top_fields(val: Any, open_by_default=False) -> str:
    """Renders dicts as expandable HTML fields, other values as <pre>."""
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                val = parsed
        except Exception:
            try:
                parsed = eval(val)
                if isinstance(parsed, dict):
                    val = parsed
            except Exception:
                pass

    if isinstance(val, dict):
        html = ""
        for i, (k, v) in enumerate(val.items()):
            if isinstance(v, (dict, list)):
                val_str = json.dumps(v, ensure_ascii=False, indent=2)
            else:
                val_str = str(v)
            details_attr = " open" if i == 0 else ""
            html += (
                f"<details class='expandfield'{details_attr}>"
                f"<summary><strong>{sanitize(str(k))}</strong></summary>"
                f"<pre>{sanitize(val_str)}</pre>"
                f"</details>"
            )
        return html or "<pre style='color:#999;'>[Empty dict]</pre>"
    elif val is None or val == "":
        return "<pre style='color:#999;'>(empty)</pre>"
    else:
        return f"<pre>{sanitize(str(val))}</pre>"


def normalize_report_metadata(report_metadata: Optional[Any]) -> Optional[Dict[str, Any]]:
    if report_metadata is None:
        return None
    if isinstance(report_metadata, dict):
        return dict(report_metadata)
    return {"value": report_metadata}


def render_report_metadata(report_metadata: Optional[Dict[str, Any]]) -> str:
    report_metadata = normalize_report_metadata(report_metadata)
    if report_metadata is None:
        return ""

    if not report_metadata:
        return (
            "<details class='run-metadata'>"
            "<summary class='run-metadata-title'>Run Details</summary>"
            "<div class='run-metadata-empty'>(empty)</div>"
            "</details>"
        )

    rows = []
    for key, value in report_metadata.items():
        if isinstance(value, (dict, list)):
            value_text = json.dumps(value, ensure_ascii=False, indent=2)
            value_html = f"<pre>{linkify(value_text)}</pre>"
        else:
            value_html = linkify(str(value))
        rows.append(
            "<div class='run-metadata-row'>"
            f"<div class='run-metadata-key'>{sanitize(str(key))}</div>"
            f"<div class='run-metadata-value'>{value_html}</div>"
            "</div>"
        )
    return (
        "<details class='run-metadata'>"
        "<summary class='run-metadata-title'>Run Details</summary>"
        "<div class='run-metadata-table'>"
        + "".join(rows)
        + "</div></details>"
    )


def format_execution_time(seconds: float) -> str:
    seconds = int(round(seconds))
    mins, secs = divmod(seconds, 60)
    return f"{mins}m {secs}s" if mins else f"{secs}s"


def _get_attr_or_key(obj, attr: str, default=None):
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


# ------------------------
# Core reporting functions
# ------------------------

def create_report(
        results: list,
        threshold: float = 0.8,
        title: str = "Test Report",
        description: str = "",
        execution_time: float = 0.0,
        save_path: Union[str, Path] = "report.html",
        scorer_weights: Optional[Dict[str, float]] = None,
        scorer_required: Optional[Dict[str, bool]] = None,
        default_thresholds: Optional[Dict[str, float]] = None,
        json_save_path: Optional[Union[str, Path]] = None,
        pass_on_any_success: bool = False,
        report_metadata: Optional[Dict[str, Any]] = None,
):
    """
    Creates and saves an HTML report with expandable entries and a JSON artifact summarizing the run.

    Args:
        pass_on_any_success: If True, a test case is marked as passed when any score in any turn passes.
            If False (default), the case passes only when all weighted/required checks pass (min-turn semantics).
        report_metadata: Optional dict to display under the report title (also included in JSON output).
    """
    passed_cases = 0
    total_cases = len(results)

    report_metadata_normalized = normalize_report_metadata(report_metadata)
    report_metadata_html = render_report_metadata(report_metadata_normalized)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8'>
  <title>{title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px; }}
    .container {{ background: #fff; padding: 30px; border-radius: 10px; max-width: 1100px; margin: auto; }}
    h1 {{ text-align: center; color: #2c3e50; }}
    .summary {{ font-size: 1rem; text-align: center; color: #444; margin-bottom: 30px; }}
    .run-metadata {{ border: 1px solid #dfe8f5; border-radius: 8px; background: #f8fbff; padding: 12px 14px; margin: 12px 0 18px; }}
    .run-metadata-title {{ font-weight: 600; color: #0f5ba5; margin-bottom: 8px; cursor: pointer; }}
    .run-metadata-table {{ display: grid; gap: 6px; }}
    .run-metadata-row {{ display: grid; grid-template-columns: 220px 1fr; gap: 12px; background: #fff; border: 1px solid #e1ebf5; border-radius: 6px; padding: 6px 10px; }}
    .run-metadata-key {{ font-weight: 600; color: #1f3b57; }}
    .run-metadata-value {{ color: #1f3b57; }}
    .run-metadata-empty {{ color: #999; font-style: italic; }}
    @media (max-width: 720px) {{ .run-metadata-row {{ grid-template-columns: 1fr; }} }}
    details.expandfield {{ border: 1px solid #e3eaf2; border-radius: 5px; background: #fafdff; margin-bottom: 4px; padding: 0 8px; }}
    details.expandfield[open] summary {{ color: #17406c; }}
    details.expandfield summary {{ font-size: 1rem; cursor: pointer; color: #0172bd; outline: none; padding: 7px 0; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th {{ background: #0277bd; color: #fff; text-align: center; font-weight: bold; font-size: 1.06rem; padding: 12px 8px; letter-spacing: .02em; }}
    td {{ text-align: left; padding: 10px; border-bottom: 1px solid #eee; vertical-align: top; font-size: 1rem; }}
    .score-pass {{ color: green; font-weight: bold; }}
    .score-fail {{ color: red; font-weight: bold; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 5px; font-weight: bold; }}
    .badge.pass {{ background: #c8e6c9; color: #1b5e20; }}
    .badge.fail {{ background: #ffcdd2; color: #b71c1c; }}
    .explanation {{ font-size: 0.95rem; margin-top: 6px; color: #555; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; font-family: Menlo, Monaco, Consolas, monospace; background: #f8f8fc; margin: 0; font-size: 0.98rem; }}
    details.testcase {{ margin-bottom: 12px; border: none; }}
    summary.testcasesum {{
      background: #f5faff; color: #1467a3; border: 1.5px solid #b3d1ed; border-radius: 7px;
      font-weight: 600; font-size: 1.07rem; padding: 12px 22px; margin: 0; cursor: pointer;
      box-shadow: 0 2px 10px 0 rgba(90,130,160,0.05);
    }}
    details.testcase[open] summary.testcasesum {{
      background: #e2f1ff; color: #113255; border: 1.5px solid #6ab1f6;
    }}
    summary.testcasesum:hover {{ background: #e9f2fc; color: #0d395d; }}
    .perf-box {{ border: 1px solid #e3eaf2; padding: 8px; border-radius: 6px; background: #fafdff; }}
    .perf-empty {{ color: #999; }}
    .perf-box details summary {{ cursor: pointer; color: #0172bd; }}
    .perf-box details {{ margin-top: 6px; }}
    .perf-box {{ background: #f8fbff; border: 1px solid #dfe8f5; border-radius: 8px; padding: 10px 12px; font-size: 0.96rem; color: #1f3b57; line-height: 1.45; }}
    .perf-label {{ font-weight: 600; margin-right: 6px; color: #0f5ba5; }}
    .perf-events {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }}
    .perf-chip {{ background: #e9f2fb; border-radius: 12px; padding: 4px 8px; font-size: 0.9rem; color: #0d3a63; border: 1px solid #d2e4f5; }}
    .perf-empty {{ color: #9aa6b8; }}
  </style>
</head>
<body>
<div class='container'>
  <h1>{title}</h1>
  {report_metadata_html}
  <p class='overview'>{description}</p>
  <div class='summary'>
    Total Test Cases: {total_cases} |
    Passed: {{passed}} |
    Failed: {{failed}} |
    Execution Time: {format_execution_time(execution_time)}
  </div>
"""

    scorer_weights = scorer_weights or {}
    default_thresholds = default_thresholds or {"float_scale": threshold, "true_false": 1.0}
    scorer_required = scorer_required or {}

    def identifier_key(identifier: Optional[Dict[str, Any]]) -> Optional[str]:
        if not identifier:
            return None
        try:
            return json.dumps(identifier, sort_keys=True)
        except Exception:
            return None

    def resolve_threshold(score_type: str) -> float:
        return float(default_thresholds.get(score_type, threshold))

    def resolve_weight(key: Optional[str]) -> float:
        if key and key in scorer_weights:
            return float(scorer_weights[key])
        return 1.0

    def resolve_required(key: Optional[str]) -> bool:
        if key and key in scorer_required:
            return bool(scorer_required[key])
        return False

    processed_results: List[Dict[str, Any]] = []
    json_results: List[Dict[str, Any]] = []

    for idx, result in enumerate(results, start=1):
        objective = _get_attr_or_key(result, "objective") or _get_attr_or_key(result, "prompt") or "N/A"
        transcript = _get_attr_or_key(result, "transcript") or []
        aggregated = result.get("aggregated_metrics", {})
        metadata = _get_attr_or_key(result, "metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        test_case_id = metadata.get("test_case_id")
        test_case_id_display = sanitize(str(test_case_id)) if test_case_id is not None else None
        turns = aggregated.get("total_turns", len(transcript))

        case_passed = False
        required_failed = False
        turn_averages: List[float] = []
        any_score_passed = False

        for turn in transcript:
            for piece in turn.get("pieces", []):
                if piece.get("role", "").lower() != "assistant":
                    continue

                weighted_sum = 0.0
                weight_total = 0.0
                numeric_values: List[float] = []

                for score in piece.get("scores", []):
                    score_type = score.get("score_type", "float_scale")
                    numeric_score = float(score.get("score", 0.0))
                    identifier = score.get("scorer_identifier")
                    key = identifier_key(identifier)

                    threshold_value = resolve_threshold(score_type)
                    weight_value = resolve_weight(key)
                    required_flag = resolve_required(key)

                    passed_score = numeric_score >= threshold_value

                    score["threshold"] = threshold_value
                    score["passed"] = passed_score
                    score["weight"] = weight_value
                    score["required"] = required_flag

                    if passed_score:
                        any_score_passed = True

                    numeric_values.append(numeric_score)
                    weighted_sum += weight_value * numeric_score
                    weight_total += weight_value

                    if required_flag and not passed_score:
                        required_failed = True

                if numeric_values:
                    if pass_on_any_success:
                        # For red team / simulation reports, ignore weighting and keep the best score this turn.
                        turn_score = max(numeric_values)
                    else:
                        if weight_total > 0:
                            turn_score = weighted_sum / weight_total
                        else:
                            turn_score = sum(numeric_values) / len(numeric_values)
                    piece["weighted_average"] = turn_score
                    turn_averages.append(turn_score)

        if not turn_averages:
            final_score = 0.0
        else:
            # Dataset-style (default): worst turn (min). Simulation/RT style: best turn (max).
            final_score = max(turn_averages) if pass_on_any_success else min(turn_averages)

        weighted_failed = final_score < threshold

        failure_reason_code = None
        if pass_on_any_success:
            case_passed = any_score_passed
            if not case_passed:
                if required_failed:
                    failure_reason_code = "required"
                elif weighted_failed:
                    failure_reason_code = "weighted"
        else:
            if required_failed:
                case_passed = False
                failure_reason_code = "required"
            elif weighted_failed:
                case_passed = False
                failure_reason_code = "weighted"
            else:
                case_passed = True

        if case_passed:
            passed_cases += 1

        processed_results.append({
            "objective": sanitize(objective),
            "transcript": transcript,
            "turns": turns,
            "final_score": final_score,
            "passed": case_passed,
            "failure_reason": failure_reason_code,
            "original_index": idx,
            "test_case_id": test_case_id_display,
        })

        json_results.append({
            "objective": objective,
            "transcript": transcript,
            "aggregated_metrics": aggregated,
            "turns": turns,
            "final_score": final_score,
            "passed": case_passed,
            "failure_reason": failure_reason_code,
            "required_failed": required_failed,
            "weighted_failed": weighted_failed,
            "original_index": idx,
            "metadata": metadata,
            "test_case_id": test_case_id,
        })

    processed_results.sort(key=lambda item: (item["passed"], item["original_index"]))
    json_results_sorted = sorted(json_results, key=lambda item: (item["passed"], item["original_index"]))

    for result_data in processed_results:
        badge = "pass" if result_data["passed"] else "fail"
        label = "Pass" if result_data["passed"] else "Fail"

        if result_data.get("test_case_id") is not None:
            lead = f"Test Case {result_data['original_index']}: <strong>Case ID:</strong> {result_data['test_case_id']}"
        else:
            lead = f"Test Case {result_data['original_index']}: <strong>Objective:</strong> {result_data['objective']}"

        summary = (
            f"{lead} | "
            f"<strong>Achieved:</strong> <span class='badge {badge}'>{label}</span> | "
            f"<strong>Turns:</strong> {result_data['turns']} | "
            f"<strong>Score:</strong> {result_data['final_score']:.2f}"
        )
        if not result_data["passed"] and result_data.get("failure_reason"):
            reason_code = result_data.get("failure_reason")
            if reason_code == "required":
                detail_text = "Required Scorer"
            elif reason_code == "weighted":
                detail_text = "Weighted Score"
            else:
                detail_text = "Failure"
            summary += f" | <strong>Reason:</strong> {sanitize(detail_text)}"

        html += f"<details class='testcase'><summary class='testcasesum'>{summary}</summary><table>"
        html += "<thead><tr><th>User</th><th>Assistant</th><th>Performance</th><th>Scores</th></tr></thead><tbody>"

        for turn in result_data["transcript"]:
            user_piece = next((p for p in turn["pieces"] if p["role"] == "user"), {"converted_value": ""})
            assistant_piece = next((p for p in turn["pieces"] if p["role"] == "assistant"), {"converted_value": "", "scores": []})

            user_text = sanitize(user_piece["converted_value"])
            assistant_html = render_expandable_top_fields(assistant_piece["converted_value"], open_by_default=False)
            latency_ms = assistant_piece.get("latency_ms")
            event_latencies = assistant_piece.get("latency_events_ms")
            latency_first = assistant_piece.get("latency_first_token_ms")

            perf_html_parts: List[str] = []
            if latency_ms is not None:
                perf_html_parts.append(f"Total: {latency_ms} ms")

            events_html = ""
            if isinstance(event_latencies, dict) and event_latencies:
                sorted_events = sorted(event_latencies.items(), key=lambda kv: kv[1])
                event_rows = "".join(
                    [f"<div><strong>{sanitize(evt)}:</strong> {lat} ms</div>" for evt, lat in sorted_events]
                )
                events_html = f"<details><summary>Event timings</summary>{event_rows}</details>"

            perf_html_body = ""
            if perf_html_parts or events_html:
                perf_html_body = "<div class='perf-box'>"
                if perf_html_parts:
                    perf_html_body += "<div>" + " | ".join(perf_html_parts) + "</div>"
                if events_html:
                    perf_html_body += events_html
                perf_html_body += "</div>"
            else:
                perf_html_body = "<div class='perf-box perf-empty'>n/a</div>"

            sorted_scores = sorted(
                assistant_piece.get("scores", []),
                key=lambda s: 0 if s.get("scorer_role") == "objective" else 1
            )

            if sorted_scores:
                scores_html = "<details><summary>Scorers</summary>"
                for score in sorted_scores:
                    identifier = score.get("scorer_identifier") or {}
                    label_text = identifier.get("__type__", "Scorer")
                    config_path = identifier.get("config_path")
                    rationale = sanitize(score.get("rationale", ""))
                    expected = score.get("expected_output")
                    threshold_val = score.get("threshold")
                    passed_val = score.get("passed", False)
                    weight_val = score.get("weight", 1.0)
                    required_flag = score.get("required", False)
                    score_type = score.get("score_type", "float_scale")
                    raw_value = score.get("raw_score", score.get("score"))
                    numeric_value = float(score.get("score", 0.0))

                    if score_type == "true_false":
                        value_display = "✔️ True" if str(raw_value).lower() == "true" else "❌ False"
                        if threshold_val is None:
                            threshold_display = "True"
                        elif threshold_val >= 1.0:
                            threshold_display = "True"
                        elif threshold_val <= 0.0:
                            threshold_display = "False"
                        else:
                            threshold_display = f"{threshold_val:.2f}"
                    else:
                        value_display = f"{numeric_value:.2f}"
                        threshold_display = f"{threshold_val:.2f}" if threshold_val is not None else "-"

                    cls = "score-pass" if passed_val else "score-fail"

                    scores_html += "<div>"
                    scores_html += f"<div><strong>{sanitize(label_text)}</strong>"
                    if required_flag:
                        scores_html += "<span style='margin-left:6px;color:#b71c1c;font-weight:600'>(Required)</span>"
                    if config_path:
                        scores_html += f"<span style='margin-left:10px;color:#888;font-size:0.9rem;'>{sanitize(config_path)}</span>"
                    scores_html += "</div>"

                    scores_html += (
                        f"<div><span class='{cls}'>{value_display}</span>"
                        f"<span style='margin-left:12px;color:#555;'>Threshold: {threshold_display}</span>"
                        f"<span style='margin-left:12px;color:#555;'>Weight: {weight_val:.2f}</span>"
                    )
                    if expected:
                        scores_html += (
                            f"<span style='margin-left:12px;color:#9a27ad;'><b>Expected:</b> {sanitize(expected)}</span>"
                        )
                    scores_html += "</div>"
                    if rationale:
                        scores_html += f"<div class='explanation'>{rationale}</div>"
                    scores_html += "</div>"
                if assistant_piece.get("weighted_average") is not None:
                    scores_html += (
                        f"<div style='margin-top:8px;color:#2c3e50;'><strong>Weighted Average:</strong> "
                        f"{assistant_piece['weighted_average']:.2f}</div>"
                    )
                scores_html += "</details>"
            else:
                scores_html = "<pre style='color:#999;'>(no scores)</pre>"

            html += f"<tr><td>{user_text}</td><td>{assistant_html}</td><td>{perf_html_body}</td><td>{scores_html}</td></tr>"

        html += "</tbody></table></details>"

    html = html.replace("{passed}", str(passed_cases)).replace("{failed}", str(total_cases - passed_cases))
    html += "</div></body></html>"

    if isinstance(save_path, str):
        save_path = Path(save_path)
    base_html_path = save_path

    if json_save_path is None:
        json_candidate: Optional[Path] = base_html_path.with_suffix(".json")
    else:
        json_candidate = Path(json_save_path)
    json_output_path: Optional[Path]
    if json_candidate is not None:
        if json_candidate.suffix == "":
            json_candidate = json_candidate / f"{base_html_path.stem}.json"
        json_output_path = json_candidate
    else:
        json_output_path = None

    timestamp_dt = datetime.now()
    timestamp = timestamp_dt.strftime("%Y%m%d_%H%M%S")
    final_html_path = base_html_path.with_name(f"{base_html_path.stem}_{timestamp}{base_html_path.suffix}")
    final_json_path: Optional[Path] = None

    if json_output_path is not None:
        final_json_path = json_output_path.with_name(
            f"{json_output_path.stem}_{timestamp}{json_output_path.suffix}"
        )

    with open(final_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    json_payload = {
        "title": title,
        "description": description,
        "threshold": threshold,
        "execution_time_seconds": execution_time,
        "generated_at": timestamp_dt.isoformat(),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "scorer_weights": dict(scorer_weights),
        "scorer_required": dict(scorer_required),
        "default_thresholds": dict(default_thresholds),
        "cases": json_results_sorted,
        "report_html": str(final_html_path),
    }

    if report_metadata_normalized is not None:
        json_payload["report_metadata"] = report_metadata_normalized
        json_payload["run_details"] = report_metadata_normalized

    if final_json_path is not None:
        json_payload["report_json"] = str(final_json_path)
        with open(final_json_path, "w", encoding="utf-8") as json_file:
            json.dump(json_payload, json_file, ensure_ascii=False, indent=2)

    print(f"\n✅ Report saved to: {final_html_path}")
    if final_json_path is not None:
        print(f"📄 JSON report saved to: {final_json_path}")

    return html


from contextlib import closing
from sqlalchemy.orm import joinedload
from pyrit.memory.memory_models import PromptMemoryEntry, ScoreEntry


async def get_conversation_report_async(attack_result) -> dict:
    memory = CentralMemory.get_memory_instance()

    with closing(memory.get_session()) as session:
        entries = (
            session.query(PromptMemoryEntry)
            .options(joinedload(PromptMemoryEntry.scores))
            .filter(PromptMemoryEntry.conversation_id == str(attack_result.conversation_id))
            .order_by(PromptMemoryEntry.sequence)
            .all()
        )

    if not entries:
        return {"error": "No conversation with the target"}

    transcript = []
    scores_by_turn = []
    turn_index = 1
    i = 0
    n = len(entries)

    while i < n:
        turn_data = {"turn_index": turn_index, "pieces": []}

        # user
        if i < n and entries[i].role.lower() == "user":
            turn_data["pieces"].append(_entry_to_piece(entries[i], is_assistant=False))
            i += 1

        # assistant
        if i < n and entries[i].role.lower() == "assistant":
            piece = _entry_to_piece(entries[i], is_assistant=True)
            turn_data["pieces"].append(piece)
            if piece["scores"]:
                scores_by_turn.append({
                    "turn_index": turn_index,
                    "score_details": piece["scores"]
                })
            i += 1

        transcript.append(turn_data)
        turn_index += 1

    # compute final score (last assistant with scores)
    final_score = None
    for turn in reversed(transcript):
        for piece in reversed(turn["pieces"]):
            if piece["role"] == "assistant" and piece["scores"]:
                final_score = piece["scores"][0].get("score")
                break
        if final_score is not None:
            break

    return {
        "objective": attack_result.objective,
        "achieved_objective": (attack_result.outcome == attack_result.outcome.__class__.SUCCESS),
        "attack_identifier": attack_result.attack_identifier,
        "executed_turns": attack_result.executed_turns,
        "outcome": attack_result.outcome.value,
        "outcome_reason": attack_result.outcome_reason,
        "metadata": attack_result.metadata,
        "conversation_id": attack_result.conversation_id,
        "transcript": transcript,
        "aggregated_metrics": {
            "total_turns": len(transcript),
            "final_score": final_score,
            "scores_by_turn": scores_by_turn,
        }
    }


def _entry_to_piece(entry, is_assistant: bool) -> dict:
    piece = {
        "role": entry.role,
        "original_value": entry.original_value or "",
        "converted_value": entry.converted_value or "",
        "scores": []
    }
    if entry.prompt_metadata:
        if isinstance(entry.prompt_metadata, dict):
            piece["prompt_metadata"] = dict(entry.prompt_metadata)
            if "latency_ms" in entry.prompt_metadata:
                piece["latency_ms"] = entry.prompt_metadata.get("latency_ms")
            if "latency_first_token_ms" in entry.prompt_metadata:
                piece["latency_first_token_ms"] = entry.prompt_metadata.get("latency_first_token_ms")
            if "latency_events_ms" in entry.prompt_metadata:
                piece["latency_events_ms"] = entry.prompt_metadata.get("latency_events_ms")

    if is_assistant and entry.scores:
        for s in entry.scores:
            score_type = getattr(s, "score_type", "float_scale")
            raw_value = s.score_value
            numeric_score: float
            raw_display = raw_value

            if score_type == "true_false":
                truthy = str(raw_value).lower() == "true"
                numeric_score = 1.0 if truthy else 0.0
                raw_display = "true" if truthy else "false"
            else:
                try:
                    numeric_score = float(raw_value)
                except Exception:
                    numeric_score = 0.0

            piece["scores"].append(
                {
                    "score": numeric_score,
                    "raw_score": raw_display,
                    "score_type": score_type,
                    "rationale": s.score_rationale,
                    "scorer_role": s.scorer_role,
                    "expected_output": s.expected_output,
                    "scorer_identifier": s.scorer_class_identifier or {},
                    "score_category": s.score_category,
                }
            )

    return piece
