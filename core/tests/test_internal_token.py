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

import time

import httpx
import pytest
from alltrue.control._internal.token import TokenRetriever
from alltrue.http.cache import CachableHttpClient
from alltrue.utils.config import AlltrueConfig


@pytest.mark.asyncio
async def test_get_internal_access_token(httpx_mock):
    def _response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"access_token": time.time()},
        )

    httpx_mock.add_callback(_response)

    config = AlltrueConfig(
        api_url="https://example.com",
        api_key="key",
        customer_id="customer_id",
        llm_api_provider="any",
    )
    retriever = TokenRetriever(
        config=config,
        client=CachableHttpClient(
            base_url="https://example.com",
        ),
    )
    token = await retriever.get_token(refresh=True)
    assert token is not None
    assert token == await retriever.get_token()
