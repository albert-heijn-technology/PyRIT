# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Union
import json
from pyrit.memory import CentralMemory

# ------------------------
# Utility functions
# ------------------------

def sanitize(text: str) -> str:
    """Sanitize text for HTML display (except for trusted HTML snippets)."""
    return str(text).replace("<", "&lt;").replace(">", "&gt;")


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
        save_path: Union[str, Path] = "report.html"
):
    """
    Creates and saves an HTML report with expandable entries.
    """
    passed_cases = 0
    total_cases = len(results)

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
  </style>
</head>
<body>
<div class='container'>
  <h1>{title}</h1>
  <p class='overview'>{description}</p>
  <div class='summary'>
    Total Test Cases: {total_cases} |
    Passed: {{passed}} |
    Failed: {{failed}} |
    Execution Time: {format_execution_time(execution_time)}
  </div>
"""

    def safe_float(val):
        try:
            return float(val)
        except Exception:
            return 1.0 if str(val).lower() == "true" else 0.0
    processed_results: List[Dict[str, Any]] = []

    for idx, result in enumerate(results, start=1):
        objective = _get_attr_or_key(result, "objective") or _get_attr_or_key(result, "prompt") or "N/A"
        transcript = _get_attr_or_key(result, "transcript") or []
        aggregated = result.get("aggregated_metrics", {})
        turns = aggregated.get("total_turns", len(transcript))

        # ---- Final score logic
        turn_averages = []
        for turn in transcript:
            assistant_piece = next(
                (p for p in turn.get("pieces", []) if p.get("role", "").lower() == "assistant" and p.get("scores")), None
            )
            if assistant_piece and assistant_piece.get("scores"):
                scores = [safe_float(s.get("score", 0)) for s in assistant_piece["scores"]]
                if scores:
                    turn_averages.append(sum(scores) / len(scores))
        final_score = min(turn_averages) if turn_averages else 0.0

        passed = final_score >= threshold
        if passed:
            passed_cases += 1

        processed_results.append({
            "objective": sanitize(objective),
            "transcript": transcript,
            "turns": turns,
            "final_score": final_score,
            "passed": passed,
            "original_index": idx,
        })

    processed_results.sort(key=lambda item: (item["passed"], item["original_index"]))

    for result_data in processed_results:
        badge = "pass" if result_data["passed"] else "fail"
        label = "Pass" if result_data["passed"] else "Fail"

        summary = (
            f"Test Case {result_data['original_index']}: <strong>Objective:</strong> {result_data['objective']} | "
            f"<strong>Achieved:</strong> <span class='badge {badge}'>{label}</span> | "
            f"<strong>Turns:</strong> {result_data['turns']} | <strong>Final Score:</strong> {result_data['final_score']:.2f}"
        )

        html += f"<details class='testcase'><summary class='testcasesum'>{summary}</summary><table>"
        html += "<thead><tr><th>User</th><th>Assistant</th><th>Scores</th></tr></thead><tbody>"

        for turn in result_data["transcript"]:
            user_piece = next((p for p in turn["pieces"] if p["role"] == "user"), {"converted_value": ""})
            assistant_piece = next((p for p in turn["pieces"] if p["role"] == "assistant"), {"converted_value": "", "scores": []})

            user_text = sanitize(user_piece["converted_value"])
            assistant_html = render_expandable_top_fields(assistant_piece["converted_value"], open_by_default=False)

            sorted_scores = sorted(
                assistant_piece.get("scores", []),
                key=lambda s: 0 if s.get("scorer_role") == "objective" else 1
            )

            if sorted_scores:
                scores_html = "<details><summary>Scorers</summary>"
                for score in sorted_scores:
                    val = score.get("score")
                    rationale = sanitize(score.get("rationale", ""))
                    expected = score.get("expected_output")
                    try:
                        val_float = float(val)
                    except:
                        val_float = True if str(val).lower() == "true" else False
                    cls = "score-pass" if (isinstance(val_float, (int, float)) and val_float >= threshold) or val_float is True else "score-fail"
                    if isinstance(val_float, bool):
                        val_display = "✔️ True" if val_float else "❌ False"
                    else:
                        val_display = f"{val_float:.2f}"
                    scores_html += f"<div><strong class='{cls}'>{val_display}</strong>"
                    if expected:
                        scores_html += f"<span style='margin-left:12px;color:#9a27ad;'><b>Expected:</b> {sanitize(expected)}</span>"
                    scores_html += f"<div class='explanation'>{rationale}</div></div>"
                scores_html += "</details>"
            else:
                scores_html = "<pre style='color:#999;'>(no scores)</pre>"

            html += f"<tr><td>{user_text}</td><td>{assistant_html}</td><td>{scores_html}</td></tr>"

        html += "</tbody></table></details>"

    html = html.replace("{passed}", str(passed_cases)).replace("{failed}", str(total_cases - passed_cases))
    html += "</div></body></html>"

    if isinstance(save_path, str):
        save_path = Path(save_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = save_path.with_name(f"{save_path.stem}_{timestamp}{save_path.suffix}")

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Report saved to: {save_path}")
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

    if is_assistant:
        if entry.scores:
            piece["scores"] = []
            for s in entry.scores:
                try:
                    score_val = float(s.score_value)
                except Exception:
                    score_val = s.score_value  # keep as-is if not numeric
                piece["scores"].append({
                    "score": score_val,
                    "rationale": s.score_rationale,
                    "scorer_role": s.scorer_role,
                    "expected_output": s.expected_output,
                })

    return piece



