# loader.py
import yaml
from pathlib import Path
from typing import Any, Dict, List, Union, Tuple


def load_test_data(file_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """
    Loads test cases from a YAML file and returns a normalized list of QA dictionaries.
    Supports both conversational and single-turn test cases.

    For conversational tests, the YAML is assumed to have the key "conversation" with a list of turns.
    For single-turn tests, expects keys "question" and "expected_outcomes" (note the plural)
    and converts them to use "expected_outcome".
    """
    path = Path(file_path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    qa_pairs = []
    for entry in data:
        test_case_id = entry.get("test_case_id")
        # Handle multi-turn conversational test cases.
        if "conversation" in entry:
            # Optionally, you could validate each turn inside the conversation.
            qa_entry = dict(entry)
            if test_case_id is not None:
                qa_entry["test_case_id"] = test_case_id
            qa_pairs.append(qa_entry)
        # Handle single-turn test cases.
        elif "question" in entry and ("expected_outcome" in entry or "expected_outcomes" in entry):
            expected_value = entry.get("expected_outcome", entry.get("expected_outcomes"))
            qa_entry = {
                "question": entry["question"],
                "expected_outcome": expected_value,
            }
            if test_case_id is not None:
                qa_entry["test_case_id"] = test_case_id
            qa_pairs.append(qa_entry)
        else:
            raise ValueError(f"Unknown test case format in entry: {entry}")

    return qa_pairs
