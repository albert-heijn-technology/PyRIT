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
        # Handle multi-turn conversational test cases.
        if "conversation" in entry:
            # Optionally, you could validate each turn inside the conversation.
            qa_pairs.append(entry)
        # Handle single-turn test cases.
        elif "question" in entry and "expected_outcome" in entry:
            # Convert the key "expected_outcomes" to "expected_outcome"
            qa_pairs.append({
                "question": entry["question"],
                "expected_outcome": entry["expected_outcome"]
            })
        else:
            raise ValueError(f"Unknown test case format in entry: {entry}")

    return qa_pairs

def extract_single_turn_tests(
        file_path: Union[str, Path]
) -> Tuple[List[str], List[str]]:
    """Parses single QA format YAML files into prompt/expected lists."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not all("question" in item and "expected_outcome" in item for item in data):
        raise ValueError("Invalid single-turn QA format")

    prompt_list = [item["question"] for item in data]
    expected_output_list = [item["expected_outcome"] for item in data]

    return prompt_list, expected_output_list

def extract_conversational_tests(
        file_path: Union[str, Path]
) -> Tuple[List[str], List[str]]:
    """Parses conversational format YAML files into flattened prompt/expected lists."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not all("conversation" in item for item in data):
        raise ValueError("Invalid conversational QA format")

    prompt_list = []
    expected_output_list = []

    for case in data:
        for turn in case["conversation"]:
            prompt_list.append(turn["question"])
            expected_output_list.append(turn["expected_outcome"])

    return prompt_list, expected_output_list