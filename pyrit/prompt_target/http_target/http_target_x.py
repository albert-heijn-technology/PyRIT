import aiohttp
import json
import re
from typing import Any, Callable, Optional, Union, Sequence, Dict

from pyrit.models import PromptRequestResponse, PromptRequestPiece, construct_response_from_request
from pyrit.prompt_target import PromptTarget, limit_requests_per_minute

RequestBody = Union[dict[str, Any], str]

class HTTPTargetX(PromptTarget):
    def __init__(
            self,
            http_request: str,
            *,
            prompt_regex_string: str = "{PROMPT}",
            use_tls: bool = True,
            response_parser: Optional[Callable[[Any], Any]] = None,
            thread_id_parser: Optional[Callable[[Any], Optional[str]]] = None,
            max_requests_per_minute: Optional[int] = None,
            client: Optional[aiohttp.ClientSession] = None,
            **client_kwargs: Any,
    ):
        super().__init__(max_requests_per_minute=max_requests_per_minute)
        self.http_request = http_request
        self.prompt_regex_string = prompt_regex_string
        self.use_tls = use_tls
        self.response_parser = response_parser
        self.thread_id_parser = thread_id_parser
        self.client_kwargs = client_kwargs or {}
        self._client = client

        if client and client_kwargs:
            raise ValueError("Cannot provide both a pre-configured client and additional client kwargs.")

    def _inject_prompt_into_request(self, request: PromptRequestPiece) -> str:
        re_pattern = re.compile(self.prompt_regex_string)
        if re.search(self.prompt_regex_string, self.http_request):
            http_request_w_prompt = re_pattern.sub(request.converted_value, self.http_request)
        else:
            http_request_w_prompt = self.http_request
        return http_request_w_prompt

    @limit_requests_per_minute
    async def send_prompt_async(self, *, prompt_request: PromptRequestResponse) -> PromptRequestResponse:
        self._validate_request(prompt_request=prompt_request)
        request = prompt_request.request_pieces[0]
        http_request_w_prompt = self._inject_prompt_into_request(request)
        header_dict, http_body, url, http_method, http_version = self.parse_raw_http_request(http_request_w_prompt)

        if "Content-Length" in header_dict:
            header_dict["Content-Length"] = str(len(http_body))

        # Use a pre-configured aiohttp.ClientSession or create a new one.
        if self._client is not None:
            client = self._client
            cleanup_client = False
        else:
            client = aiohttp.ClientSession(**self.client_kwargs)
            cleanup_client = True

        try:
            # If body is JSON/dict, send as json, else as data.
            if isinstance(http_body, dict):
                async with client.request(
                        method=http_method,
                        url=url,
                        headers=header_dict,
                        json=http_body,
                ) as response:
                    response_text = await response.text()
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        try:
                            parsed_input = await response.json()
                        except Exception:
                            parsed_input = json.loads(response_text)
                    else:
                        parsed_input = response_text
            else:
                async with client.request(
                        method=http_method,
                        url=url,
                        headers=header_dict,
                        data=http_body,
                ) as response:
                    response_text = await response.text()
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        try:
                            parsed_input = await response.json()
                        except Exception:
                            parsed_input = json.loads(response_text)
                    else:
                        parsed_input = response_text

            # Call the parser function (should accept str or dict)
            if self.response_parser:
                processed_response = self.response_parser(parsed_input)
                # Check if stream ended properly
                if isinstance(processed_response, dict):
                    stream_ended = processed_response.get("StreamEnded", "").strip().lower()
                    if stream_ended != "true":
                        raise RuntimeError("Stream ended unexpectedly — no STREAMING_ENDED received.")
            else:
                processed_response = parsed_input

            thread_id = None
            if self.thread_id_parser:
                thread_id = self.thread_id_parser(parsed_input)

            response_entry = construct_response_from_request(
                request=request,
                response_text_pieces=[str(processed_response)],
                prompt_metadata={"thread_id": thread_id} if thread_id else None,
            )
        finally:
            if cleanup_client:
                await client.close()
        return response_entry

    def parse_raw_http_request(self, http_request: str) -> tuple[Dict[str, str], RequestBody, str, str, str]:
        headers_dict: Dict[str, str] = {}
        body = ""

        request_parts = http_request.strip().split("\n\n", 1)
        header_lines = request_parts[0].strip().split("\n")
        http_req_info_line = header_lines[0].split(" ")
        header_lines = header_lines[1:]

        for line in header_lines:
            key, value = line.split(":", 1)
            headers_dict[key.strip().lower()] = value.strip()

        if "content-length" in headers_dict:
            del headers_dict["content-length"]

        if len(request_parts) > 1:
            try:
                body = json.loads(request_parts[1], strict=False)
            except json.JSONDecodeError:
                body = request_parts[1]

        if len(http_req_info_line) != 3:
            raise ValueError("Invalid HTTP request line")

        http_method = http_req_info_line[0]
        url_path = http_req_info_line[1]
        full_url = self._infer_full_url_from_host(path=url_path, headers_dict=headers_dict)
        http_version = http_req_info_line[2]

        return headers_dict, body, full_url, http_method, http_version

    def _infer_full_url_from_host(self, path: str, headers_dict: Dict[str, str]) -> str:
        path = path.lower()
        if path.startswith(("http://", "https://")):
            return path
        http_protocol = "https://"
        if not self.use_tls:
            http_protocol = "http://"
        host = headers_dict["host"]
        return f"{http_protocol}{host}{path}"

    def _validate_request(self, *, prompt_request: PromptRequestResponse) -> None:
        pieces: Sequence[PromptRequestPiece] = prompt_request.request_pieces
        if len(pieces) != 1:
            raise ValueError("This target only supports a single prompt request piece.")
