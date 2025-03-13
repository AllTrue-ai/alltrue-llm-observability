#  Copyright 2025 AllTrue.ai
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

import json
import logging

import httpcore
from alltrue.http import HttpStatus
from alltrue.http.cache import CachableEndpoint, CachableHttpClient
from alltrue.utils.config import AlltrueConfig

logger = logging.getLogger("alltrue.token")

_TOKEN_ENDPOINT = "/v1/auth/issue-jwt-token"


def _gen_cache_key(request: httpcore.Request, body: bytes = b"") -> bytes:
    return (
        json.loads(body.decode("utf-8")).get("api_key", "invalid-key").encode("utf-8")
    )


class TokenRetriever:
    def __init__(self, config: AlltrueConfig, client: CachableHttpClient):
        self._config = config
        self._client = client
        self._client.register_cachable(
            CachableEndpoint(
                path=_TOKEN_ENDPOINT,
                methods=["POST"],
                key_generator=_gen_cache_key,
            )
        )

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
        if response.status_code == HttpStatus.OK:
            payload = response.json()
            if "access_token" in payload:
                return payload["access_token"]
            else:
                logger.warning(f"[IAK] Failed to get access token: {payload}")
                return None
        else:
            logger.warning(f"[IAK] Failed to get access token: {response.text}")
            return None
