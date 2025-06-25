# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.


import json
import re
from typing import Callable

import requests


def get_http_target_json_response_callback_function(key: str) -> Callable:
    """
    Purpose: determines proper parsing response function for an HTTP Request
    Parameters:
        key (str): this is the path pattern to follow for parsing the output response
            (ie for AOAI this would be choices[0].message.content)
            (for BIC this needs to be a regex pattern for the desired output)
        response_type (ResponseType): this is the type of response (ie HTML or JSON)
    Returns: proper output parsing response
    """

    def parse_json_http_response(response: requests.Response):
        """
        Purpose: parses json outputs
        Parameters:
            response (response): the HTTP Response to parse
        Returns: parsed output from response given a "key" path to follow
        """
        json_response = json.loads(response.content)
        data_key = _fetch_key(data=json_response, key=key)
        return data_key

    return parse_json_http_response


def get_http_target_regex_matching_callback_function(key: str, url: str = None) -> Callable:
    def parse_using_regex(response: requests.Response):
        """
        Purpose: parses text outputs using regex
        Parameters:
            url (optional str): the original URL if this is needed to get a full URL response back (ie BIC)
            key (str): this is the regex pattern to follow for parsing the output response
            response (response): the HTTP Response to parse
        Returns: parsed output from response given a regex pattern to follow
        """
        re_pattern = re.compile(key)
        match = re.search(re_pattern, str(response.content))
        if match:
            if url:
                return url + match.group()
            else:
                return match.group()
        else:
            return str(response.content)

    return parse_using_regex


def _fetch_key(data: dict, key: str):
    """
    Credit to @Mayuraggarwal1992
    Fetches the answer from the HTTP JSON response based on the path.

    Args:
        data (dict): HTTP response data.
        key (str): The key path to fetch the value.

    Returns:
        str: The fetched value.
    """
    pattern = re.compile(r"([a-zA-Z_]+)|\[(\d+)\]")
    keys = pattern.findall(key)
    for key_part, index_part in keys:
        if key_part:
            data = data.get(key_part, None)
        elif index_part and isinstance(data, list):
            data = data[int(index_part)] if len(data) > int(index_part) else None
        if data is None:
            return ""
    return data

def get_http_regex_stream_callback_function(key: str) -> Callable:
    """
    Purpose: Extracts text messages from an HTTP response using regex.
    Returns: A function that parses the HTTP response to extract text messages.
    """

    def extract_text_messages(response: requests.Response) -> str:
        """
        Purpose: Extracts text messages from the response content using regex.
        Parameters:
            response (requests.Response): The HTTP response to parse.
        Returns: The extracted text messages as a single string.
        """
        text = response.text
        # Use regex to find all occurrences of 'event:TEXT_MESSAGE' followed by 'data:'
        messages = re.findall(key, text)
        # Join the extracted message parts together into one string
        full_message = ''.join(messages)
        return full_message

    return extract_text_messages

# Cell 3: New MultiFieldResponseParser that uses the original helper functions

import json
import re
from typing import Any, Callable, List
import requests

class MultiFieldResponseParser:
    """
    Combines JSON, single-match regex, and stream regex parsing in one class.
    For each field, it uses one of the original helper functions internally.

    Example field definition list (pass this into the constructor):
      [
        {"name": "text",    "type": "stream", "pattern": r"regex_pattern_for_text_messages"},
        {"name": "data",    "type": "regex",  "pattern": r"regex_pattern_for_data"},
        {"name": "meta",    "type": "regex",  "pattern": r"regex_pattern_for_meta"},
        {"name": "content", "type": "json",   "json_key": "json.path.to.content"},
      ]
    """

    def __init__(self, field_definitions: List[dict]):
        self.parsers: List[tuple[str, Callable[[requests.Response], Any]]] = []

        for fld in field_definitions:
            name = fld.get("name")
            type_ = fld.get("type", "").lower()
            if type_ not in {"json", "regex", "stream"}:
                raise ValueError(f"Unsupported type '{type_}' for field '{name}'.")

            if type_ == "json":
                json_key = fld.get("json_key")
                if not json_key:
                    raise ValueError(f"Field '{name}' in 'json' type requires 'json_key'.")
                parser_fn = get_http_target_json_response_callback_function(json_key)

            elif type_ == "regex":
                pattern = fld.get("pattern")
                if not pattern:
                    raise ValueError(f"Field '{name}' in 'regex' type requires 'pattern'.")

                # Wrap regex parser with JSON parse if applicable
                def make_regex_parser(pat):
                    def parser(response):
                        text = response.content.decode("utf-8", errors="replace")
                        match = re.search(pat, text)
                        if match:
                            content = match.group(1).strip()
                            # Try JSON parse if looks like JSON
                            if content.startswith("{") and content.endswith("}"):
                                try:
                                    return json.loads(content)
                                except json.JSONDecodeError:
                                    pass
                            return content
                        return ""
                    return parser

                parser_fn = make_regex_parser(pattern)

            else:  # type_ == "stream"
                pattern = fld.get("pattern")
                if not pattern:
                    raise ValueError(f"Field '{name}' in 'stream' type requires 'pattern'.")

                def make_stream_parser(pat):
                    def parser(response):
                        text = response.content.decode("utf-8", errors="replace")
                        matches = re.findall(pat, text, re.DOTALL)
                        return "".join(matches).strip() if matches else ""
                    return parser

                parser_fn = make_stream_parser(pattern)

            self.parsers.append((name, parser_fn))

    def __call__(self, response: requests.Response) -> dict[str, Any]:
        result: dict[str, Any] = {}
        raw_text = response.content.decode("utf-8", errors="replace")

        for name, fn in self.parsers:
            try:
                value = fn(response)
            except Exception:
                value = ""
            result[name] = value if value is not None else ""

        if not any(result.values()):
            return {"raw_response": raw_text}

        return result
