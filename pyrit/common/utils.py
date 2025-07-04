# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import hashlib
import logging
import math
import random
from typing import List, Optional, Union
import re
import yaml

logger = logging.getLogger(__name__)


def combine_dict(existing_dict: Optional[dict] = None, new_dict: Optional[dict] = None) -> dict:
    """
    Combines two dictionaries containing string keys and values into one.

    Args:
        existing_dict: Dictionary with existing values
        new_dict: Dictionary with new values to be added to the existing dictionary.
            Note if there's a key clash, the value in new_dict will be used.

    Returns:
        dict: combined dictionary
    """
    result = {**(existing_dict or {})}
    result.update(new_dict or {})
    return result


def combine_list(list1: Union[str, List[str]], list2: Union[str, List[str]]) -> list:
    """
    Combines two lists containing string keys, keeping only unique values.

    Args:
        existing_dict: Dictionary with existing values
        new_dict: Dictionary with new values to be added to the existing dictionary.
            Note if there's a key clash, the value in new_dict will be used.

    Returns:
        list: combined dictionary
    """
    if isinstance(list1, str):
        list1 = [list1]
    if isinstance(list2, str):
        list2 = [list2]

    # Merge and keep only unique values
    combined = list(set(list1 + list2))
    return combined

def update_yaml_with_regex(file_path, text, pattern=r'\{.*?\}'):
    with open(file_path, 'r') as file:
        yaml_content = yaml.safe_load(file)

    # Function to replace content inside curly braces with the topic, while keeping the braces
    def replace_with_topic(value):
        # Only apply the replacement if the value is a string
        if isinstance(value, str):
            return re.sub(pattern, f'{{{text}}}', value)
        return value

    # Recursively update all string fields in the YAML content
    def update_fields(data):
        if isinstance(data, dict):
            return {k: update_fields(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [update_fields(item) for item in data]
        else:
            return replace_with_topic(data)

    # Update all fields in the YAML content
    updated_content = update_fields(yaml_content)

    # Write the updated YAML content back to the file
    with open(file_path, 'w') as file:
        yaml.safe_dump(updated_content, file, default_flow_style=False, sort_keys=False)

def get_random_indices(*, start: int, size: int, proportion: float) -> List[int]:
    """
    Generate a list of random indices based on the specified proportion of a given size.
    The indices are selected from the range [start, start + size).

    Args:
        start (int): Starting index (inclusive). It's the first index that could possibly be selected.
        size (int): Size of the collection to select from. This is the total number of indices available.
            For example, if `start` is 0 and `size` is 10, the available indices are [0, 1, 2, ..., 9].
        proportion (float): The proportion of indices to select from the total size. Must be between 0 and 1.
            For example, if `proportion` is 0.5 and `size` is 10, 5 randomly selected indices will be returned.

    Returns:
        List[int]: A list of randomly selected indices based on the specified proportion.
    """
    if start < 0:
        raise ValueError("Start index must be non-negative")
    if size <= 0:
        raise ValueError("Size must be greater than 0")
    if proportion < 0 or proportion > 1:
        raise ValueError("Proportion must be between 0 and 1")

    if proportion == 0:
        return []
    if proportion == 1:
        return list(range(start, start + size))

    n = max(math.ceil(size * proportion), 1)  # the number of indices to select
    return random.sample(range(start, start + size), n)


def to_sha256(data: str) -> str:
    """
    Converts a string to its SHA-256 hash representation.

    Args:
        data (str): The input string to be hashed.

    Returns:
        str: The SHA-256 hash of the input string, represented as a hexadecimal string.
    """
    return hashlib.sha256(data.encode()).hexdigest()
