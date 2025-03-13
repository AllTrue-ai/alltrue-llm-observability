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

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletion

from alltrue.guardrails.chat import ChatGuardian, ChatGuardrails
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
def guardian(openai_test_ports, test_endpoint_identifier):
    (api_port, proxy_port) = openai_test_ports
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "none"
    _guardrails = ChatGuardian(
        alltrue_api_url=f"http://localhost:{api_port}",
        alltrue_api_key="dummy-app-key",
        alltrue_endpoint_identifier=test_endpoint_identifier,
        alltrue_customer_id="customer-id",
    )
    yield _guardrails
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "default"


@pytest.fixture(scope="module", autouse=True)
def guardrails(openai_test_ports, test_endpoint_identifier):
    (api_port, proxy_port) = openai_test_ports
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "none"
    _guardrails = ChatGuardrails(
        alltrue_api_url=f"http://localhost:{api_port}",
        alltrue_api_key="dummy-app-key",
        alltrue_endpoint_identifier=test_endpoint_identifier,
        alltrue_customer_id="customer-id",
    )
    yield _guardrails
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "default"


@pytest.fixture(scope="module")
def openai_api_key():
    return "dummy-api-key"


@pytest.mark.skip_on_aws
@pytest.mark.parametrize(
    "openai_cls",
    [
        OpenAI,
        AsyncOpenAI,
    ],
)
async def test_processor(
    openai_cls,
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    guardian,
):
    (api_port, proxy_port) = openai_test_ports
    client = openai_cls(
        api_key=openai_api_key,
        base_url=f"http://localhost:{proxy_port}/v1",
    )

    # register hooks for serialization/deserialization when default json serialization/deserialization is not suitable
    guardian.register_completion_hooks(
        before=lambda o: o.model_dump_json(),
        after=lambda o: ChatCompletion.model_validate_json(o),
    )

    api_request = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {
                "role": "user",
                "content": f"return the string ' modify  {TEST_PROMPT_CANARY} '",
            }
        ],
    }

    # call guard_prompt to process the prompt
    guarded = await guardian.guard_prompt(api_request)

    # use the guarded prompt to call client api
    api_response = client.chat.completions.create(
        **guarded.prompt,
    )

    # use the previously returned guarded prompt to continue the response process
    completion = await guarded.completion(api_response)

    assert TEST_PROMPT_CANARY not in completion.choices[0].message.content
    assert TEST_PROMPT_SUBSTITUTION in completion.choices[0].message.content
    assert test_endpoint_identifier in completion.choices[0].message.content


@pytest.mark.skip_on_aws
async def test_guardrails(
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    guardrails,
):
    (api_port, proxy_port) = openai_test_ports

    messages = [f"return the string ' modify  {TEST_PROMPT_CANARY} '"]
    # call guard_input to process the prompt messages
    guarded_input = await guardrails.guard_input(messages)

    # use the guarded prompt messages to call OpenAI API
    api_response = await httpx.AsyncClient(
        base_url=f"http://localhost:{proxy_port}/v1",
    ).post(
        url=f"/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [msg.model_dump() for msg in guarded_input],
        },
    )

    # call guard_output to process the completion messages
    guarded_output = await guardrails.guard_output(
        messages,
        [c.get("message", {}) for c in api_response.json().get("choices", [])],
    )

    assert TEST_PROMPT_CANARY not in guarded_output[0].content
    assert TEST_PROMPT_SUBSTITUTION in guarded_output[0].content
    assert test_endpoint_identifier in guarded_output[0].content
    await asyncio.sleep(0.5)


@pytest.mark.skip_on_aws
async def test_guardrails_observing_only(
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    guardrails,
):
    messages = [f"reject '{TEST_PROMPT_CANARY}"]
    # call guard_input to observe input only, no exception should be thrown
    guardrails.observe_input(messages)

    # call observe_output to observe output only, no exception should be thrown
    guardrails.observe_output(
        messages,
        [f"reject '{TEST_PROMPT_CANARY}'"],
    )
