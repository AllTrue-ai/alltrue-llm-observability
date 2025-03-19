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

from ...utils.logfire import configure_logfire  # isort:skip

logfire = configure_logfire()  # isort:skip

import json
import logging

import httpcore

from ...http import HttpStatus
from ...http.cache import CachableEndpoint, CachableHttpClient
from ...utils.config import AlltrueConfig

_TOKEN_ENDPOINT = "/v1/auth/issue-jwt-token"


def _gen_cache_key(request: httpcore.Request, body: bytes = b"") -> bytes:
    return (
        json.loads(body.decode("utf-8")).get("api_key", "invalid-key").encode("utf-8")
    )


class TokenRetriever:
    """
    Retrieve access token from Alltrue API.
    """

    def __init__(
        self,
        config: AlltrueConfig,
        client: CachableHttpClient,
        logging_level: int | str = logging.INFO,
    ):
        self.log = logging.getLogger("alltrue.api.token")
        self.log.setLevel(logging_level)

        self._config = config
        self._client = client
        self._client.register_cachable(
            CachableEndpoint(
                path=_TOKEN_ENDPOINT,
                methods=["POST"],
                key_generator=_gen_cache_key,
            )
        )

    @logfire.instrument()
    async def get_token(
        self,
        refresh: bool = False,
    ) -> str | None:
        """
        This function is used to get the internal access token
        :param refresh: force to retrieve a fresh access token and then recache it, if successful
        :return: internal access token or dummy string `__placeholder__` if unable to retrieve it
        """
        response = await self._client.post(
            url=_TOKEN_ENDPOINT,
            json={
                "api_key": self._config.api_key,
            },
            extensions={"cache_disabled": True} if refresh else {"force_cache": True},
        )
        if HttpStatus.is_success(response.status_code):
            payload = response.json()
            if "access_token" in payload:
                return payload["access_token"]
            else:
                self.log.warning(f"Failed to get access token: {payload}")
                return None
        else:
            self.log.warning(f"Failed to get access token: {response.text}")
            return None
