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

import asyncio
import os
import time

import pytest
from openai import AsyncOpenAI, OpenAI

from alltrue_guardrails.observers.openai import OpenAIObserver
from .. import TEST_PROMPT_CANARY, TEST_PROMPT_SUBSTITUTION, TESTS_DIR, init_servers


@pytest.fixture(scope="module")
def openai_test_ports():
    (api_process, api_port, proxy_process, proxy_port) = init_servers(
        target_url="https://api.openai.com",
    )
    # to wait a bit to ensure the system is up
    cert_file = os.path.join(
        TESTS_DIR, "_mitmproxy", str(proxy_port), "mitmproxy-ca.pem"
    )
    waited = 0
    while waited < 5 and not os.path.exists(cert_file):
        time.sleep(1)
        waited += 1

    yield api_port, proxy_port

    proxy_process.terminate()
    api_process.terminate()


@pytest.fixture(scope="module")
def blocking():
    return False


@pytest.fixture
async def openai_client(
    request, openai_test_ports, blocking, openai_api_key, test_endpoint_identifier
):
    (api_port, proxy_port) = openai_test_ports
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "none"
    observer = OpenAIObserver(
        alltrue_api_url=f"http://localhost:{api_port}",
        alltrue_api_key="dummy-app-key",
        alltrue_endpoint_identifier="dummy-endpoint-identifier",
        blocking=blocking,
        logging_level="DEBUG",
        _batch_size=4,
        _queue_time=0.5,
    )
    observer.register()
    _cls = request.param
    yield _cls(
        api_key=openai_api_key,
        base_url=f"http://localhost:{proxy_port}/v1",
        default_headers={
            "x-alltrue-llm-endpoint-identifier": test_endpoint_identifier,
        },
    )
    observer.unregister()
    await asyncio.sleep(3)
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "default"


@pytest.fixture(scope="module")
def openai_api_key():
    return "dummy-api-key"


@pytest.mark.skip_on_remote
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "openai_client",
    [
        OpenAI,
        AsyncOpenAI,
    ],
    indirect=True,
)
async def test_openai(
    openai_client,
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    blocking,
):
    for i in range(1 if blocking else 10):
        completion = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": f"return the string ' modify  {TEST_PROMPT_CANARY} ' - {i}",
                }
            ],
        )
        if asyncio.iscoroutine(completion):
            completion = await completion

        assert (TEST_PROMPT_CANARY in completion.choices[0].message.content) != blocking
        assert (
            TEST_PROMPT_SUBSTITUTION not in completion.choices[0].message.content
        ) != blocking
        assert (
            test_endpoint_identifier not in completion.choices[0].message.content
        ) != blocking
        await asyncio.sleep(0.05 * i)
    await asyncio.sleep(2)
