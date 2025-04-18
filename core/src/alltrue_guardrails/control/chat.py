#  Copyright 2025 AllTrue.ai Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

from ..utils.logfire import configure_logfire
import functools
import json
import logging
import re
from datetime import UTC, datetime
from json import JSONDecodeError
from typing import NamedTuple, Literal

import httpcore
import httpx

from ..http import HttpMethod, HttpStatus
from ..http.cache import CachableEndpoint
from . import AlltrueAPIClient


LLM_API_KEY_PATTERN = re.compile(r"(x-[\w\-]*key|[aA]uthorization)$")
logfire = configure_logfire()


def _parse_url(
    url: str,
    scheme: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> dict[str, str | int]:
    _origin = httpcore.URL(url).origin
    return {
        "url": url,
        "host": host or _origin.host.decode("utf-8"),
        "port": port or _origin.port,
        "scheme": scheme or _origin.scheme.decode("utf-8"),
    }


def _gen_cache_key(
    request: httpcore.Request, body: bytes = b"", logger: logging.Logger | None = None
) -> bytes:
    """
    Cache key composed by api key and url path
    """
    try:
        json_body = json.loads(body.decode("utf-8"))
        endpoint_identifier = json_body.get("endpoint_identifier", None)
        if endpoint_identifier is not None:
            return endpoint_identifier.encode("utf-8")

        headers = json_body.get("headers", [])
        if len(headers) == 0:
            headers = json_body.get("llm_api_request", {}).get("request_headers", [])
        for attr, val in dict(
            json.loads(headers) if isinstance(headers, str) else headers
        ).items():
            if LLM_API_KEY_PATTERN.match(attr) is not None:
                return val.encode("utf-8")
    except JSONDecodeError:
        if logger:
            logger.debug("Skip body parsing for generating cache key")
    return body


class ProcessResult(NamedTuple):
    content: str
    status_code: int
    message: str | None = None

    @property
    def new_body(self) -> str:
        # for backward compatibility
        return self.content


class RuleProcessor(AlltrueAPIClient):
    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        llm_api_provider: str | None = None,
        logging_level: int | str = logging.INFO,
        **kwargs,
    ):
        super().__init__(
            api_url=api_url,
            api_key=api_key,
            llm_api_provider=llm_api_provider,
            logging_level=logging_level,
            **kwargs,
        )
        self._client.register_cachable(
            CachableEndpoint(
                path="/v1/llm-firewall/chat/check-connection/",
                methods=["POST"],
                key_generator=functools.partial(
                    _gen_cache_key,
                    logger=self.log,
                ),
            )
        )
        self._client.register_cachable(
            CachableEndpoint(
                path="/v1/ai-usage/quarantine/llm-endpoint",
                methods=["POST"],
                key_generator=functools.partial(
                    _gen_cache_key,
                    logger=self.log,
                ),
            )
        )

    @logfire.instrument("Calling AI Usage API")
    async def check_usage(
        self,
        endpoint_identifier: str | None = None,
        headers: list[tuple[str, str]] | None = None,
        llm_api_provider: str | None = None,
        timeout: float = 0.5,
        cache: bool = False,
        **kwargs,
    ) -> bool:
        """
        Check if the usage of LLM endpoint is sanctioned
        """
        body: dict = {}
        if endpoint_identifier:
            body["endpoint_identifier"] = endpoint_identifier
        elif headers is not None:
            body["llm_api_request"] = {
                "provider": llm_api_provider or self.config.llm_api_provider,
                "request_headers": dict(headers),
            }
        else:
            self.log.warning("Invalid endpoint info for usage check")
            return False

        response = await super()._request(
            endpoint="/v1/ai-usage/quarantine/llm-endpoint",
            body=body,
            timeout=timeout,
            cache=cache,
        )
        if HttpStatus.is_success(response.status_code):
            return response.json().get("sanctioned", True)
        else:
            return True

    @logfire.instrument("Calling LLM Chat API: {endpoint=}")
    async def _chat(
        self,
        endpoint: str,
        method: HttpMethod = "POST",
        body: dict | None = None,
        timeout: float | None = None,
        cache: bool = False,
    ) -> httpx.Response:
        return await super()._request(
            endpoint=f"/v1/llm-firewall/chat/{endpoint.removeprefix('/')}",
            method=method,
            body=body,
            timeout=timeout,
            cache=cache,
        )

    async def check_connection(
        self,
        endpoint_identifier: str,
        llm_api_provider: str | None = None,
        headers: list[tuple[str, str]] | None = None,
        timeout: float = 0.5,
        cache: bool = False,
        **kwargs,
    ) -> bool:
        """
        Check if the LLM endpoint is connectable
        """
        reply = await self._chat(
            endpoint=f"/check-connection/{llm_api_provider or self.config.llm_api_provider}",
            body={
                "endpoint_identifier": endpoint_identifier,
                "headers": json.dumps(dict(headers) if headers else {}),
            },
            timeout=timeout,
            cache=cache,
        )
        if not HttpStatus.is_success(reply.status_code):
            self.log.warning(
                f"Check failed: {reply.status_code}-{reply.text}",
            )
            return False
        return True

    async def process_request(
        self,
        *,
        body: str,
        request_id: str,
        endpoint_identifier: str,
        url: str = "https://httpbin.org",
        method: HttpMethod = "POST",
        headers: list[tuple[str, str]] | None = None,
        host: str | None = None,
        port: int | None = None,
        scheme: str | None = None,
        client_ip: str = "192.0.2.0",
        client_port: int = 0,
        start_time: float = datetime.timestamp(
            datetime.now(UTC)
        ),  # unix timestamp of flow start
        llm_api_provider: str | None = None,
        **kwargs,
    ) -> ProcessResult | None:
        """
        Call the Control Plane API with this info about the request and get back a new body
        :param body: The original body of the request
        :param request_id: A UUID to connect the request and response
        :param url: The URL of the request
        :param method: HTTP method of the requesst - POST, GET, etc.
        :param headers: all headers in the request
        :param host: Target host of the call
        :param port: Target port of the call
        :param scheme: http or https
        :param client_ip: Client IP address
        :param client_port: Client port
        :param endpoint_identifier: optional endpoint identifier
        :param start_time
        :param llm_api_provider
        :return: If we don't want to touch the request, return None. Else return a tuple: [new_body, status_code]
                 If we want to return 403 Forbidden, return ["forbidden", 403]
                 similarly, If we want to return a new body, return [new_body, 200]
        """
        api_req_body = {
            "original_request_body": body,
            "completion_request_id": request_id,
            "method": method,
            "headers": headers or [],
            "client_ip": client_ip,
            "client_port": client_port,
            "endpoint_identifier": endpoint_identifier,
            "start_time": start_time,
            **_parse_url(url, scheme=scheme, host=host, port=port),
        }

        # for custom proxy deployments, the proxy type is included in the base URL the user calls. So if provided,
        # we "override" the configured value. Otherwise, it's expected to be in an environment variable.
        proxy_type = llm_api_provider or self.config.llm_api_provider

        try:
            reply = await self._chat(
                f"/process-input/{proxy_type}",
                body=api_req_body,
            )
            if not HttpStatus.is_success(reply.status_code):
                self.log.warning(
                    f"Failed to call Control Plane input API: {reply.status_code}-{reply.text}",
                )
                return None

            self.log.debug(f"Replied {reply.text}")
            reply_body_json = json.loads(reply.text)
            body = reply_body_json["processed_input"]
            if isinstance(body, dict):
                body = json.dumps(body)

            return ProcessResult(
                content=body,
                status_code=reply_body_json["status_code"],
                message=reply_body_json.get("message"),
            )
        except (JSONDecodeError, KeyError) as e:
            self.log.exception(
                "Failed to parse Control Plane input API response",
                exc_info=e,
            )
            return None
        except Exception as e:
            self.log.exception(
                "Failed to call Control Plane input API",
                exc_info=e,
            )
            return None

    async def process_response(
        self,
        *,
        body: str,
        original_request_input: str,
        request_id: str,
        endpoint_identifier: str,
        url: str = "https://httpbin.org",
        request_headers: list[tuple[str, str]] | None = None,
        response_headers: list[tuple[str, str]] | None = None,
        client_ip: str = "192.0.2.0",
        client_port: int = 0,
        host: str | None = None,
        method: HttpMethod = "POST",
        port: int | None = None,
        scheme: str | None = None,
        start_time: float = datetime.timestamp(
            datetime.now(UTC)
        ),  # unix timestamp of flow start
        llm_api_provider: str | None = None,
        **kwargs,
    ) -> ProcessResult | None:
        """
        Call the Control Plane API with this info about the response and get back a new body
        :param original_request_input: Text of the original HTTP request
        :param url: The URL of the request
        :param method: HTTP method of the requesst - POST, GET, etc.
        :param host: Target host of the call
        :param port: Target port of the call
        :param scheme: http or https
        :param body: The original body of the request
        :param request_id: A UUID to connect the request and response
        :param request_headers: all headers in the request
        :param response_headers: all headers in the request
        :param client_ip: Client IP address
        :param client_port: Client port,
        :param endpoint_identifier: optional endpoint identifier
        :param start_time
        :param llm_api_provider
        :return: If we don't want to touch the request, return None. Else, return a tuple: [new_body, status_code]
                 If we want to return 403 Forbidden, return ["forbidden", 403]
                 similarly, If we want to return a new body, return [new_body, 200]

        """
        api_req_body = {
            "original_response_body": body,
            "original_request_body": original_request_input,
            "completion_request_id": request_id,
            "headers": request_headers or [],
            "response_headers": response_headers or [],
            "client_ip": client_ip,
            "client_port": client_port,
            "endpoint_identifier": endpoint_identifier,
            "method": method,
            "start_time": start_time,
            **_parse_url(url, scheme=scheme, host=host, port=port),
        }

        # for custom proxy deployments, the proxy type is included in the base URL the user calls. So if provided,
        # we "override" the configured value. Otherwise, it's expected to be in an environment variable.
        proxy_type = llm_api_provider or self.config.llm_api_provider

        try:
            reply = await self._chat(
                f"/process-output/{proxy_type}",
                body=api_req_body,
            )
            if reply.status_code < 200 or reply.status_code > 299:
                self.log.warning(
                    f"Failed to call Control Plane output API: {reply.status_code}-{reply.text}",
                )
                return None

            self.log.debug("Replied %s", reply.text)
            reply_body_json = json.loads(reply.text)
            body = reply_body_json["processed_output"]
            if isinstance(body, dict):
                body = json.dumps(body)
            return ProcessResult(
                content=body,
                status_code=reply_body_json["status_code"],
                message=reply_body_json.get("message"),
            )
        except (JSONDecodeError, KeyError) as e:
            self.log.exception(
                "Failed to parse Control Plane output API response",
                exc_info=e,
            )
            return None
        except Exception as e:
            self.log.exception(
                "Failed to call Control Plane output API",
                exc_info=e,
            )
            return None

    async def process_prompt(
        self,
        request_id: str,
        endpoint_identifier: str,
        prompt_input: str,
        prompt_output: str | None = None,
        validation: Literal["connection", "usage", None] = None,
        quick_response: bool = True,
        **kwargs,
    ) -> ProcessResult | None:
        """
        Shortcut function to validate and then process prompt input/output with minimum required parameters.
        Three validation types to choose from:
         1) connection - validate the connectivity of the endpoint and skip process when invalid
         2) usage - validate the usage of the endpoint and return forbidden result when unsanctioned
         3) None - default, no validation before the process of prompt
        """
        headers = kwargs.pop(
            "headers",
            [
                ("Content-Type", "application/json"),
            ],
        )
        if not quick_response:
            headers.append(("x-alltrue-llm-cache-control", "no-cache"))
            kwargs["cache"] = False
        else:
            kwargs["cache"] = True

        if validation == "usage":
            if not await self.check_usage(
                endpoint_identifier=endpoint_identifier,
                headers=headers,
                **kwargs,
            ):
                return ProcessResult(
                    content="",
                    status_code=HttpStatus.FORBIDDEN,
                    message="Unsanctioned endpoint",
                )
        elif validation == "connection":
            if not await self.check_connection(
                endpoint_identifier=endpoint_identifier,
                headers=headers,
                **kwargs,
            ):
                return None

        if prompt_output is None:
            return await self.process_request(
                request_id=request_id,
                endpoint_identifier=endpoint_identifier,
                body=prompt_input,
                headers=headers,
                **kwargs,
            )
        else:
            return await self.process_response(
                request_id=request_id,
                endpoint_identifier=endpoint_identifier,
                body=prompt_output,
                original_request_input=prompt_input,
                request_headers=headers,
                **kwargs,
            )

    async def get_processed_traces(
        self,
        request_id: str,
    ):
        """
        Get the processed traces of the particular request session
        """
        reply = await self._chat(
            endpoint=f"/session/{request_id}",
            method="GET",
            cache=False,
        )
        if HttpStatus.is_success(reply.status_code):
            try:
                session = json.loads(reply.text)
                content = {
                    "id": request_id,
                    "llm_provider_name": session.get("llm_provider_name"),
                    "llm_model_name": session.get("llm_model_name"),
                }
                for req_type in ["input", "output"]:
                    req = session.get(f"{req_type}_request")
                    if req:
                        content.update(
                            {
                                f"{req_type}_process": {
                                    "at": req.get("created_at"),
                                    "actions": [
                                        action.get("action_json")
                                        for action in req.get(f"{req_type}_actions", [])
                                    ],
                                }
                            }
                        )

                return ProcessResult(
                    status_code=reply.status_code,
                    content=json.dumps(content),
                )
            except (JSONDecodeError, KeyError) as e:
                self.log.exception(
                    "Failed to parse session query response",
                    exc_info=e,
                )
        return None

    @property
    async def is_running(self) -> bool:
        # TODO: complete the closure and reopen procedure
        return True

    async def close(self, timeout: float | None = None) -> None:
        # TODO: complete the closure and reopen procedure
        # await asyncio.wait_for(self._client.aclose(), timeout=timeout)
        pass
