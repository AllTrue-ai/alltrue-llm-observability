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

import asyncio
import os
import time

import pytest
from openai import AsyncOpenAI, OpenAI

from alltrue.observers.openai import OpenAIObserver
from tests import TEST_PROMPT_CANARY, TEST_PROMPT_SUBSTITUTION, TESTS_DIR, init_servers


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


@pytest.fixture(scope="module", autouse=True)
def observer(openai_test_ports):
    (api_port, proxy_port) = openai_test_ports
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "none"
    observer = OpenAIObserver(
        alltrue_api_url=f"http://localhost:{api_port}",
        alltrue_api_key="dummy-app-key",
        alltrue_customer_id="dummy-customer-id",
        alltrue_endpoint_identifier="dummy-endpoint-identifier",
        blocking=False,
        logging_level="DEBUG",
    )
    observer.register()
    yield
    observer.unregister()
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "default"


@pytest.fixture(scope="module")
def openai_api_key():
    return "dummy-api-key"


@pytest.mark.skip_on_aws
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "openai_cls",
    [
        OpenAI,
        AsyncOpenAI,
    ],
)
async def test_openai(
    openai_cls,
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
):
    (api_port, proxy_port) = openai_test_ports

    client = openai_cls(
        api_key=openai_api_key,
        base_url=f"http://localhost:{proxy_port}/v1",
        default_headers={
            "x-alltrue-llm-endpoint-identifier": test_endpoint_identifier,
        },
    )
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "user",
                "content": f"return the string ' modify  {TEST_PROMPT_CANARY} '",
            }
        ],
    )
    if asyncio.iscoroutine(completion):
        completion = await completion
    assert TEST_PROMPT_CANARY in completion.choices[0].message.content
    assert TEST_PROMPT_SUBSTITUTION not in completion.choices[0].message.content
    assert test_endpoint_identifier not in completion.choices[0].message.content
    await asyncio.sleep(1)


@pytest.mark.skip_on_aws
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "openai_cls",
    [
        OpenAI,
        AsyncOpenAI,
    ],
)
async def test_openai_no_rule(
    openai_cls,
    openai_api_key,
    openai_test_ports: tuple[int, int],
):
    (api_port, proxy_port) = openai_test_ports

    client = openai_cls(
        api_key=openai_api_key,
        base_url=f"http://localhost:{proxy_port}/v1",
        default_headers={"x-alltrue-llm-endpoint-identifier": "__no_rule__"},
    )
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "user",
                "content": f"print the string 'rewrite-reply {TEST_PROMPT_CANARY}' ",
            },
        ],
    )
    if asyncio.iscoroutine(completion):
        completion = await completion
    assert TEST_PROMPT_CANARY in completion.choices[0].message.content
    await asyncio.sleep(1)
