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
import logging
from abc import ABC

import httpx

from ..http import HttpMethod, HttpStatus
from ..http.cache import CachableHttpClient
from ..utils.config import AlltrueConfig
from ._internal.token import TokenRetriever

MAX_TOKEN_REFRESH_RETRIES = 3

logfire = configure_logfire()


class AlltrueAPIClient(ABC):
    """
    Client to interact with Alltrue APIs
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        llm_api_provider: str | None = None,
        logging_level: int | str = logging.INFO,
        _timeout: float | None = None,
        _retries: int | None = None,
        _keep_alive: bool | None = None,
        **kwargs,
    ):
        self.log = logging.getLogger("alltrue.api.client")
        self.log.setLevel(logging_level)

        _config = kwargs.pop("_config", None)
        if isinstance(_config, AlltrueConfig):
            self.config = _config
        else:
            self.config = AlltrueConfig(
                api_url=api_url,
                api_key=api_key,
                llm_api_provider=llm_api_provider,
            )
            self.log.info(
                f"Initiated with config: {self.config.model_dump_json(indent=2, exclude={'llm_api_provider'})}"
            )

        _client = kwargs.pop("_client", None)
        if isinstance(_client, CachableHttpClient):
            self._client = _client
        else:
            self._client = CachableHttpClient(
                base_url=self.config.api_url,  # type: ignore
                logger=self.log,
                keep_alive=_keep_alive,
                timeout=_timeout,
                retries=_retries,
            )
        self._token_manager = TokenRetriever(
            config=self.config,
            client=self._client,
            logging_level=logging_level,
        )

    async def _request(
        self,
        endpoint: str,
        method: HttpMethod = "POST",
        body: dict | None = None,
        timeout: float | None = None,
        cache: bool = False,
    ) -> httpx.Response:
        """
        Call the Control Plane API , retrying if we get a 403 Forbidden in case token has expired
        :param endpoint: The chat api endpoint
        :param method: The HTTP method to use
        :param body: The original body of the request
        :param timeout: timeout setting per request level if given
        :param cache: Should cache the response when sufficient
        :return: HTTPX reply
        """
        token_error_count = 0
        while token_error_count < MAX_TOKEN_REFRESH_RETRIES:
            token = await self._token_manager.get_token(
                refresh=token_error_count > 0,
            )
            if token:
                self.log.debug(f"{method} {endpoint} | token: {token} | body: {body}")
                reply = await self._client.request(
                    method=method,
                    url=endpoint,
                    json=body,
                    headers={
                        "content-type": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    timeout=timeout,
                    extensions={"force_cache": True}
                    if cache
                    else {"cache_disabled": True},
                )

                if not HttpStatus.is_unauthorized(reply.status_code):
                    return reply

            token_error_count += 1
            self.log.info(
                "Auth failed with Control Plane API,"
                f"retrying {token_error_count} out of {MAX_TOKEN_REFRESH_RETRIES}"
            )
        else:
            self.log.warning(
                "Failed too many times for retrieving a valid token. Giving up."
            )
            return httpx.Response(
                status_code=HttpStatus.UNAUTHORIZED,
                content="Too many token refresh errors. Giving up.",
            )
