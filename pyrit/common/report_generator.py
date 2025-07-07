from pyrit.memory import CentralMemory
import json
from pathlib import Path
from typing import Any, Dict, List, Union

def sanitize(text: str) -> str:
    """Sanitize text for HTML display (except for trusted HTML snippets)."""
    return str(text).replace("<", "&lt;").replace(">", "&gt;")

def render_expandable_top_fields(val: Any) -> str:
    """
    Renders the top-level keys of a dict (or stringified dict) as expandable fields.
    All other types (lists, strings, etc.) are shown as <pre>.
    """
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
        for k, v in val.items():
            if isinstance(v, (dict, list)):
                val_str = json.dumps(v, ensure_ascii=False, indent=2)
            else:
                val_str = str(v)
            html += (
                f"<details class='expandfield'>"
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

def create_report(
        results: list,
        threshold: float = 0.8,
        title: str = "Test Report",
        description: str = "",
        execution_time: float = 0.0,
        is_chat_eval: bool = False,
        strict_step_failures: bool = True,
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
    th {{ 
      background: #0277bd; color: #fff; 
      text-align: center; /* center header text */
      font-weight: bold; 
      font-size: 1.06rem;
      padding: 12px 8px;
      letter-spacing: .02em;
    }}
    td {{ 
      text-align: left;  /* left-align cell content */
      padding: 10px;
      border-bottom: 1px solid #eee;
      vertical-align: top;
      font-size: 1rem;
    }}
    .score-pass {{ color: green; font-weight: bold; }}
    .score-fail {{ color: red; font-weight: bold; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 5px; font-weight: bold; }}
    .badge.pass {{ background: #c8e6c9; color: #1b5e20; }}
    .badge.fail {{ background: #ffcdd2; color: #b71c1c; }}
    .explanation {{ font-size: 0.95rem; margin-top: 6px; color: #555; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; font-family: Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; background: #f8f8fc; margin: 0; font-size: 0.98rem; }}

    /* --- Button-style Test Case Entry --- */
    details.testcase {{ margin-bottom: 12px; border: none; }}
    summary.testcasesum {{
      background: #f5faff;
      color: #1467a3;
      border: 1.5px solid #b3d1ed;
      border-radius: 7px;
      font-weight: 600;
      font-size: 1.07rem;
      padding: 12px 22px;
      margin-bottom: 0;
      margin-top: 0;
      cursor: pointer;
      outline: none;
      box-shadow: 0 2px 10px 0 rgba(90,130,160,0.05);
      transition: background .12s, border .14s;
      user-select: none;
    }}
    details.testcase[open] summary.testcasesum {{
      background: #e2f1ff;
      color: #113255;
      border: 1.5px solid #6ab1f6;
    }}
    summary.testcasesum:hover {{
      background: #e9f2fc;
      color: #0d395d;
    }}
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

    for idx, result in enumerate(results, start=1):
        objective = _get_attr_or_key(result, "objective") or _get_attr_or_key(result, "prompt") or "N/A"
        objective = sanitize(objective)

        transcript = _get_attr_or_key(result, "transcript")
        if transcript is None:
            prompt = result.get("prompt")
            response = result.get("assistant_response")
            scores = result.get("scores", [])
            if prompt is not None and response is not None:
                pieces = [
                    {"role": "user", "converted_value": prompt, "scores": []},
                    {"role": "assistant", "converted_value": response, "scores": scores}
                ]
                transcript = [{"turn_index": 1, "pieces": pieces}]
            else:
                transcript = _get_attr_or_key(result, "conversation", [])

        has_expected = False
        if not is_chat_eval:
            for turn in transcript:
                for piece in turn.get("pieces", []):
                    for score in piece.get("scores", []):
                        if score.get("expected_output"):
                            has_expected = True
                            break
                    if has_expected:
                        break
                if has_expected:
                    break

        aggregated = result.get("aggregated_metrics", {})
        turns = aggregated.get("total_turns", len(transcript))
        final_score = aggregated.get("final_score")
        if final_score is None:
            if len(transcript) == 1:
                assistant = next((p for p in transcript[0]["pieces"] if p["role"] == "assistant"), {})
                vals = [float(s.get("score", s.get("score_value", 0))) for s in assistant.get("scores", [])]
                final_score = max(vals, default=0.0)
            else:
                final_score = 0.0

        score_values = []
        for turn in transcript:
            for piece in turn["pieces"]:
                for score in piece.get("scores", []):
                    val = score.get("score", score.get("score_value", 0))
                    try:
                        score_values.append(float(val))
                    except:
                        score_values.append(1.0 if str(val).lower() == "true" else 0.0)

        score_to_float = lambda v: 1.0 if str(v).strip().lower() in ("true", "1") else 0.0 if str(v).strip().lower() in ("false", "0") else float(v)
        passed = all(score_to_float(s) >= threshold for s in score_values) if strict_step_failures else score_to_float(final_score) >= threshold
        if passed:
            passed_cases += 1

        badge = "pass" if passed else "fail"
        label = "Pass" if passed else "Fail"

        summary = f"Test Case {idx}: <strong>Objective:</strong> {objective} | <strong>Achieved:</strong> <span class='badge {badge}'>{label}</span> | <strong>Turns:</strong> {turns}"
        if isinstance(final_score, (int, float)):
            summary += f" | <strong>Final Score:</strong> {final_score:.2f}"

        # Button-style collapsible test case entry
        html += f"<details class='testcase'><summary class='testcasesum'>{summary}</summary><table>"

        if not is_chat_eval:
            if has_expected:
                html += "<thead><tr><th>User</th><th>Assistant</th><th>Expected Output</th><th>Score</th></tr></thead><tbody>"
            else:
                html += "<thead><tr><th>User</th><th>Assistant</th><th>Score</th></tr></thead><tbody>"
        else:
            html += "<thead><tr><th>User</th><th>Assistant</th><th>Score</th></tr></thead><tbody>"

        for turn in transcript:
            user_piece = next((p for p in turn["pieces"] if p["role"] == "user"), {"converted_value": ""})
            assistant_piece = next((p for p in turn["pieces"] if p["role"] == "assistant"), {"converted_value": "", "scores": []})

            user_text = sanitize(user_piece["converted_value"])
            assistant_val = assistant_piece["converted_value"]

            assistant_html = render_expandable_top_fields(assistant_val)

            scores_html = ""
            expected_html = sanitize(assistant_piece["scores"][0].get("expected_output", "")) if has_expected else None
            for score in assistant_piece.get("scores", []):
                val = score.get("score", score.get("score_value", None))
                rationale = sanitize(score.get("rationale", score.get("score_rationale", "N/A")))
                try:
                    val = float(val)
                except:
                    val = True if str(val).lower() == "true" else False
                cls = "score-pass" if (isinstance(val, (int, float)) and val >= threshold) or val is True else "score-fail"
                if isinstance(val, bool):
                    val_display = "✔️ True" if val else "❌ False"
                else:
                    val_display = f"{val:.2f}"
                scores_html += f"<div><strong class='{cls}'>{val_display}</strong><div class='explanation'>{rationale}</div></div>"

            if not is_chat_eval:
                if has_expected:
                    html += f"<tr><td>{user_text}</td><td>{assistant_html}</td><td>{expected_html}</td><td>{scores_html}</td></tr>"
                else:
                    html += f"<tr><td>{user_text}</td><td>{assistant_html}</td><td>{scores_html}</td></tr>"
            else:
                html += f"<tr><td>{user_text}</td><td>{assistant_html}</td><td>{scores_html}</td></tr>"

        html += "</tbody></table></details>"

    html = html.replace("{passed}", str(passed_cases)).replace("{failed}", str(total_cases - passed_cases))
    html += "</div></body></html>"

    # --- Save to disk ---
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Report saved to: {save_path}")
    return html

async def get_conversation_report_async(attack_result) -> dict:
    """
    Returns a structured conversation report for HTML reporting or metrics.
    """
    memory = CentralMemory.get_memory_instance()
    target_messages = memory.get_conversation(conversation_id=attack_result.conversation_id)
    if not target_messages:
        return {"error": "No conversation with the target"}

    report: Dict[str, Any] = {}
    transcript: List[Dict] = []
    scores_by_turn: List[Dict] = []

    report["objective"] = attack_result.objective
    report["achieved_objective"] = (attack_result.outcome == attack_result.outcome.__class__.SUCCESS)
    report["attack_identifier"] = attack_result.attack_identifier
    report["executed_turns"] = attack_result.executed_turns
    report["outcome"] = attack_result.outcome.value
    report["outcome_reason"] = attack_result.outcome_reason
    report["metadata"] = attack_result.metadata
    report["conversation_id"] = attack_result.conversation_id

    turn_index = 1
    i = 0
    n = len(target_messages)

    while i < n:
        turn_data = {"turn_index": turn_index, "pieces": []}
        if i < n:
            turn_data["pieces"].extend(
                _build_piece_data(
                    target_messages[i],
                    turn_index=turn_index,
                    scores_by_turn=scores_by_turn,
                    is_assistant=False
                )
            )
            i += 1
        if i < n:
            turn_data["pieces"].extend(
                _build_piece_data(
                    target_messages[i],
                    turn_index=turn_index,
                    scores_by_turn=scores_by_turn,
                    is_assistant=True
                )
            )
            i += 1
        transcript.append(turn_data)
        turn_index += 1

    # Locate final_score from last assistant piece
    final_score = None
    for turn in reversed(transcript):
        for piece in reversed(turn["pieces"]):
            if piece.get("role", "").lower() == "assistant" and piece.get("scores"):
                final_score = piece["scores"][0].get("score")
                break
        if final_score is not None:
            break

    report["transcript"] = transcript
    report["aggregated_metrics"] = {
        "total_turns": len(transcript),
        "final_score": final_score,
        "scores_by_turn": scores_by_turn
    }
    return report

def _build_piece_data(
        message,
        turn_index: int,
        scores_by_turn: List[Dict],
        is_assistant: bool
) -> List[Dict]:
    """
    Convert each message piece into dict with:
      - role
      - original_value
      - converted_value
      - scores (assistant only, including expected_output if present)
    """
    memory = CentralMemory.get_memory_instance()
    pieces_data: List[Dict] = []
    for piece in message.request_pieces:
        piece_data = {
            "role": piece.role,
            "original_value": piece.original_value or "",
            "converted_value": piece.converted_value or "",
            "scores": []
        }

        if is_assistant and piece.role.lower() == "assistant":
            raw_scores = memory.get_scores_by_prompt_ids(
                prompt_request_response_ids=[str(piece.id)]
            )
            if raw_scores:
                piece_scores: List[Dict] = []
                for s in raw_scores:
                    score_entry = {
                        "score": getattr(s, "score_value", None),
                        "rationale": getattr(s, "score_rationale", None)
                    }
                    if hasattr(s, "expected_output") and s.expected_output:
                        score_entry["expected_output"] = s.expected_output
                    piece_scores.append(score_entry)
                piece_data["scores"] = piece_scores
                if piece_scores:
                    scores_by_turn.append({
                        "turn_index": turn_index,
                        "score_details": piece_scores
                    })
        pieces_data.append(piece_data)
    return pieces_data
