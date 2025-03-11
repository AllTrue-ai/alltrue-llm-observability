#  Copyright 2023-2024 AllTrue.ai Inc
#  All Rights Reserved.
#
#  NOTICE: All information contained herein is, and remains
#  the property of AllTrue.ai Incorporated. The intellectual and technical
#  concepts contained herein are proprietary to AllTrue.ai Incorporated
#  and may be covered by U.S. and Foreign Patents,
#  patents in process, and are protected by trade secret or copyright law.
#  Dissemination of this information or reproduction of this material
#  is strictly forbidden unless prior written permission is obtained
#  from AllTrue.ai Incorporated.

import json
import logging
from datetime import UTC, datetime
from json import JSONDecodeError
from typing import NamedTuple

import httpcore
import httpx
from alltrue.control import LLM_API_KEY_PATTERN
from alltrue.utils.config import AlltrueConfig

from ..http import HttpMethod, HttpStatus
from ..http.cache import CachableEndpoint, CachableHttpClient
from ._internal.token import TokenRetriever

MAX_TOKEN_REFRESH_RETRIES = 5

logger = logging.getLogger("alltrue.rule")


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


def _gen_cache_key(request: httpcore.Request, body: bytes = b"") -> bytes:
    """
    Cache key composed by api key and url path
    """
    try:
        headers = json.loads(body.decode("utf-8")).get("headers", [])
        for attr, val in dict(
            json.loads(headers) if isinstance(headers, str) else headers
        ).items():
            if LLM_API_KEY_PATTERN.match(attr) is not None:
                return val.encode("utf-8")
    except JSONDecodeError:
        logger.debug("[CPA] Skip body parsing for generating cache key")
    return body


class ProcessResult(NamedTuple):
    new_body: str
    status_code: int
    message: str | None = None


class RuleProcessor:
    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        customer_id: str | None = None,
        llm_api_provider: str | None = None,
        _connection_keep_alive: str | None = None,
    ):
        self.config = AlltrueConfig(
            api_url=api_url,
            api_key=api_key,
            customer_id=customer_id,
            llm_api_provider=llm_api_provider,
        )
        self._client = CachableHttpClient(
            base_url=self.config.api_url,  # type: ignore
            _keep_alive=_connection_keep_alive,
        )
        self._client.register_cachable(
            CachableEndpoint(
                path="/v1/llm-firewall/chat/check-connection/",
                methods=["POST"],
                key_generator=_gen_cache_key,
            )
        )
        self._token_manager = TokenRetriever(config=self.config, client=self._client)

    async def _call_control(
        self, endpoint: str, body: dict, cache: bool = False
    ) -> httpx.Response:
        """
        Call the Control Plane API , retrying if we get a 403 Forbidden in case token has expired
        :param endpoint: The chat api endpoint
        :param body: The original body of the request
        :return: HTTPX reply
        """
        token_error_count = 0
        while token_error_count < MAX_TOKEN_REFRESH_RETRIES:
            token = await self._token_manager.get_token(
                refresh=token_error_count > 0,
            )
            if token:
                logger.debug(
                    f"[CPA] Request to control\n endpoint: {endpoint}\n token: {token}\n body: {body}\n"
                )
                reply = await self._client.post(
                    url=f"/v1/llm-firewall/chat/{endpoint.removeprefix('/')}",
                    json=body,
                    headers={
                        "content-type": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    extensions={"force_cache": True}
                    if cache
                    else {"cache_disabled": True},
                )

                if reply.status_code not in (
                    HttpStatus.UNAUTHORIZED,
                    HttpStatus.FORBIDDEN,
                ):
                    return reply

            token_error_count += 1
            logger.warning(
                "[CPA] Auth failed with Control Plane API,"
                f"retrying {token_error_count} out of {MAX_TOKEN_REFRESH_RETRIES}"
            )
        else:
            logger.error(
                "[CPA] Failed too many times for retrieving a valid token. Giving up."
            )
            return httpx.Response(
                status_code=HttpStatus.UNAUTHORIZED,
                content=f"Too many token refresh errors. Giving up.",
            )

    async def check_connection(
        self,
        endpoint_identifier: str,
        llm_api_provider: str | None = None,
        headers: list[tuple[str, str]] | None = None,
        cache: bool = False,
    ) -> bool:
        """
        Check the given endpoint identifier is valid
        """
        reply = await self._call_control(
            endpoint=f"/check-connection/{llm_api_provider or self.config.llm_api_provider}",
            body={
                "customer_id": self.config.customer_id,
                "endpoint-identifier": endpoint_identifier,
                "headers": json.dumps(dict(headers) if headers else {}),
            },
            cache=cache,
        )
        if reply.status_code != HttpStatus.OK:
            logger.warning(
                f"[CPA] Check failed: {reply.status_code}-{reply.text}",
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
            "customer_id": self.config.customer_id,
            "endpoint_identifier": endpoint_identifier,
            "start_time": start_time,
            **_parse_url(url, scheme=scheme, host=host, port=port),
        }

        # for custom proxy deployments, the proxy type is included in the base URL the user calls. So if provided,
        # we "override" the configured value. Otherwise, it's expected to be in an environment variable.
        proxy_type = llm_api_provider or self.config.llm_api_provider

        try:
            reply = await self._call_control(
                f"/process-input/{proxy_type}",
                body=api_req_body,
            )
            if reply.status_code != HttpStatus.OK:
                logger.warning(
                    f"[CPA] Failed to call Control Plane input API: {reply.status_code}-{reply.text}",
                )
                return None

            logger.debug(f"[CPA] Replied {reply.text}")
            reply_body_json = json.loads(reply.text)
            body = reply_body_json["processed_input"]
            if isinstance(body, dict):
                body = json.dumps(body)

            return ProcessResult(
                new_body=body,
                status_code=reply_body_json["status_code"],
                message=reply_body_json.get("message"),
            )
        except (JSONDecodeError, KeyError) as e:
            logger.exception(
                f"[CPA] Failed to parse Control Plane input API response",
                exc_info=e,
            )
            return None
        except Exception as e:
            logger.exception(
                f"[CPA] Failed to call Control Plane input API",
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
            "customer_id": self.config.customer_id,
            "endpoint_identifier": endpoint_identifier,
            "method": method,
            "start_time": start_time,
            **_parse_url(url, scheme=scheme, host=host, port=port),
        }

        # for custom proxy deployments, the proxy type is included in the base URL the user calls. So if provided,
        # we "override" the configured value. Otherwise, it's expected to be in an environment variable.
        proxy_type = llm_api_provider or self.config.llm_api_provider

        try:
            reply = await self._call_control(
                f"/process-output/{proxy_type}",
                body=api_req_body,
            )
            if reply.status_code < 200 or reply.status_code > 299:
                logger.warning(
                    f"[CPA] Failed to call Control Plane output API: {reply.status_code}-{reply.text}",
                )
                return None

            logger.debug("[CPA] Replied %s", reply.text)
            reply_body_json = json.loads(reply.text)
            body = reply_body_json["processed_output"]
            if isinstance(body, dict):
                body = json.dumps(body)
            return ProcessResult(
                new_body=body,
                status_code=reply_body_json["status_code"],
                message=reply_body_json.get("message"),
            )
        except (JSONDecodeError, KeyError) as e:
            logger.exception(
                f"[CPA] Failed to parse Control Plane output API response",
                exc_info=e,
            )
            return None
        except Exception as e:
            logger.exception(
                f"[CPA] Failed to call Control Plane output API",
                exc_info=e,
            )
            return None
