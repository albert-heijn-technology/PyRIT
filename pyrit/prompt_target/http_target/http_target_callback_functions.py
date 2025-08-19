# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import json
import re
from typing import Callable, List, Any

import requests


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

def get_http_regex_stream_callback_function(event_marker: str) -> Callable:
    """
    event_marker: e.g. 'event:TEXT_MESSAGE'
    Concatenate payloads exactly as sent. We trust the stream to deliver spaces/newlines explicitly.
    """
    event_marker = event_marker.strip()

    def extract_text_messages(response: str) -> str:
        if not isinstance(response, str):
            response = str(response)

        lines = response.splitlines()
        in_text_event = False
        chunks: List[str] = []

        # collapse multiple blank data: lines into a single newline
        blank_streak = 0

        def append_payload(payload: str):
            nonlocal blank_streak
            # Right-strip only line terminators; keep leading spaces intact
            chunk = payload.rstrip("\r\n")

            if chunk == "":
                blank_streak += 1
                # convert first blank in a streak to a single newline
                if blank_streak == 1:
                    chunks.append("\n")
                return
            else:
                blank_streak = 0
                chunks.append(chunk)

        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith("event:"):
                in_text_event = (line.strip() == event_marker)
                i += 1
                continue

            if in_text_event:
                if line.startswith("data:"):
                    payload = line[len("data:"):]  # keep leading space if present
                    append_payload(payload)
                    i += 1
                    continue
                else:
                    # end of this event block
                    in_text_event = False
                    # don't consume this line; outer loop will handle it
                    continue

            i += 1

        # Join verbatim. Do NOT auto-insert spaces; the stream already includes them when needed.
        out = "".join(chunks)

        # Optional: de-dup excessive blank lines
        out = re.sub(r"\n{3,}", "\n\n", out)

        return out.strip("\n")

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
