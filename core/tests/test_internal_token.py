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
