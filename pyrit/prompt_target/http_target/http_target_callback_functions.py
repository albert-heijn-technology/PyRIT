# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import re
from typing import Callable, List, Any

def get_http_target_json_response_callback_function(key: str) -> Callable:
    def parse_json_http_response(response: str):
        json_response = json.loads(response)
        return _fetch_key(json_response, key)
    return parse_json_http_response


def get_http_target_json_response_callback_function(key: str) -> Callable:
    """
    Determines proper parsing response function for an HTTP Request

    Parameters:
        key (str): this is the path pattern to follow for parsing the output response
            (ie for AOAI this would be choices[0].message.content)
            (for BIC this needs to be a regex pattern for the desired output)
        response_type (ResponseType): this is the type of response (ie HTML or JSON)

    Returns: proper output parsing response
    """

    def parse_json_http_response(response: requests.Response):
        """
        Parses JSON outputs

        Parameters:
            response (response): the HTTP Response to parse

        Returns: parsed output from response given a "key" path to follow
        """
        json_response = json.loads(response.content)
        data_key = _fetch_key(data=json_response, key=key)
        return data_key

def get_http_regex_stream_callback_function(pattern: str) -> Callable:
    compiled = re.compile(pattern + r"\s+data:(.*)", re.MULTILINE)

    def extract_text_messages(response: str) -> str:
        matches = compiled.findall(response)
        return "".join(m.rstrip("\r\n") for m in matches if m != "")

def get_http_target_regex_matching_callback_function(key: str, url: str = None) -> Callable:
    def parse_using_regex(response: requests.Response):
        """
        Parses text outputs using regex

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


def _fetch_key(data: dict, key: str):
    """
    Fetches the answer from the HTTP JSON response based on the path.

    Args:
        data (dict): HTTP response data.
        key (str): The key path to fetch the value.

    Returns:
        str: The fetched value.
    """
    pattern = re.compile(r"([a-zA-Z_]+)|\[(-?\d+)\]")
    keys = pattern.findall(key)
    for key_part, index_part in keys:
        if key_part:
            data = data.get(key_part, None)
        elif index_part and isinstance(data, list):
            data = data[int(index_part)] if -len(data) <= int(index_part) < len(data) else None
        if data is None:
            return ""
    return data

def get_http_regex_stream_callback_function(pattern: str) -> Callable:
    compiled = re.compile(pattern + r"\s+data:(.*)", re.MULTILINE)

    def extract_text_messages(response: str) -> str:
        matches = compiled.findall(response)
        return "".join(m.rstrip("\r\n") for m in matches if m != "")

    return extract_text_messages



class MultiFieldResponseParser:
    def __init__(self, field_definitions: List[dict]):
        self.parsers: List[tuple[str, Callable[[str], Any]]] = []
        for fld in field_definitions:
            name = fld.get("name")
            type_ = fld.get("type", "").lower()
            if type_ not in {"json", "regex", "stream"}:
                raise ValueError(f"Unsupported type '{type_}' for field '{name}'.")

            if type_ == "json":
                json_key = fld.get("json_key")
                if not json_key:
                    raise ValueError(f"Field '{name}' of type 'json' requires 'json_key'.")
                parser_fn = get_http_target_json_response_callback_function(json_key)
            elif type_ == "regex":
                pattern = fld.get("pattern")
                if not pattern:
                    raise ValueError(f"Field '{name}' of type 'regex' requires 'pattern'.")
                parser_fn = get_http_target_regex_matching_callback_function(pattern)
            else:  # stream
                pattern = fld.get("pattern")
                if not pattern:
                    raise ValueError(f"Field '{name}' of type 'stream' requires 'pattern'.")
                parser_fn = get_http_regex_stream_callback_function(pattern)

            self.parsers.append((name, parser_fn))

    def __call__(self, response: Any) -> dict[str, str]:
        if isinstance(response, bytes):
            response = response.decode("utf-8", errors="replace")
        elif not isinstance(response, str):
            response = str(response)

        result: dict[str, str] = {}
        for name, fn in self.parsers:
            try:
                value = fn(response)
            except Exception:
                value = ""
            result[name] = str(value).strip() if value else ""

        if not any(result.values()):
            return {"raw_response": response.strip()}

        return result
