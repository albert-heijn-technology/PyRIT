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


def get_http_target_regex_matching_callback_function(pattern: str) -> Callable:
    def parse_using_regex(response: str):
        re_pattern = re.compile(pattern, re.DOTALL)
        match = re.search(re_pattern, response)
        return match.group(1).strip() if match else ""
    return parse_using_regex


def get_http_regex_stream_callback_function(pattern: str) -> Callable:
    compiled = re.compile(pattern, re.DOTALL)

    def extract_text_messages(response: str) -> str:
        matches = compiled.findall(response)
        fragments = []

        for match in matches:
            for line in match.splitlines():
                if line.startswith("data:"):
                    content = line[5:].strip()
                    if content.lower() in {"true", "false", "null"}:
                        continue
                    if content.startswith("{"):
                        continue
                    fragments.append(content)

        sentence = " ".join(fragments)
        sentence = re.sub(r"\b([A-Z])\s+([a-z]+)", r"\1\2", sentence)
        sentence = re.sub(r"\s+([.,!?])", r"\1", sentence)
        return sentence

    return extract_text_messages



def _fetch_key(data: dict, key: str):
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
