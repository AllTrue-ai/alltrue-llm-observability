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
from alltrue_guardrails.http.cache import CachableEndpoint, CachableHttpClient


@pytest.mark.asyncio
async def test_cache_result(httpx_mock):
    def _response(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/endpoint"):
            return httpx.Response(
                status_code=200,
                json={"time": time.time()},
            )
        return httpx.Response(404)

    httpx_mock.add_callback(_response)

    client = CachableHttpClient(
        base_url="https://example.com",
        verify=False,
    )
    client.register_cachable(
        CachableEndpoint(
            path="/v1/endpoint",
            methods=["GET"],
        )
    )
    resp1 = await client.get(
        url="/v1/endpoint",
        extensions={"force_cache": True},
    )
    assert resp1.status_code == 200
    assert resp1.json().get("time", 0) > 0
    resp2 = await client.get(
        url="/v1/endpoint",
        extensions={"force_cache": True},
    )
    assert resp2.status_code == 200
    assert resp2.json().get("time", 0) == resp1.json().get("time", 0)
