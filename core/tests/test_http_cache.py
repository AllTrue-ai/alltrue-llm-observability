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
import time

import httpx
import pytest
from alltrue.http.cache import CachableEndpoint, CachableHttpClient


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
