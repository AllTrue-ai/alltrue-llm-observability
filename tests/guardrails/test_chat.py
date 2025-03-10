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
import asyncio
import os
import time

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletion

from alltrue.guardrails.chat import ChatGuardrails, ChatGuardrailsLite
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


@pytest.fixture(scope="module", autouse=True)
def guardrails_lite(openai_test_ports, test_endpoint_identifier):
    (api_port, proxy_port) = openai_test_ports
    os.environ["CONFIG_HTTP_KEEPALIVE"] = "none"
    _guardrails = ChatGuardrailsLite(
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
async def test_guardrails(
    openai_cls,
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    guardrails,
):
    (api_port, proxy_port) = openai_test_ports
    client = openai_cls(
        api_key=openai_api_key,
        base_url=f"http://localhost:{proxy_port}/v1",
    )

    # register hooks for serialization/deserialization when default json serialization/deserialization is not suitable
    guardrails.register_completion_hooks(
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
    guarded = await guardrails.guard_prompt(api_request)

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
async def test_guardrails_lite(
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    guardrails_lite,
):
    (api_port, proxy_port) = openai_test_ports

    messages = [f"return the string ' modify  {TEST_PROMPT_CANARY} '"]
    # call guard_input to process the prompt messages
    guarded_input = await guardrails_lite.guard_input(messages)

    # use the guarded prompt messages to call OpenAI API
    api_response = await httpx.AsyncClient(
        base_url=f"http://localhost:{proxy_port}/v1",
    ).post(
        url=f"/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [
                {
                    "role": "user",
                    "content": msg,
                }
                for msg in guarded_input
            ],
        },
    )

    # call guard_output to process the completion messages
    guarded_output = await guardrails_lite.guard_output(
        messages,
        [
            c.get("message", {}).get("content", "")
            for c in api_response.json().get("choices", [])
        ],
    )

    assert TEST_PROMPT_CANARY not in guarded_output[0]
    assert TEST_PROMPT_SUBSTITUTION in guarded_output[0]
    assert test_endpoint_identifier in guarded_output[0]
    await asyncio.sleep(0.5)


@pytest.mark.skip_on_aws
async def test_guardrails_lite_observing(
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    guardrails_lite,
):
    messages = [f"reject '{TEST_PROMPT_CANARY}"]
    # call guard_input to observe input only, no exception should be thrown
    guardrails_lite.observe_input(messages)

    # call observe_output to observe output only, no exception should be thrown
    guardrails_lite.observe_output(
        messages,
        [f"reject '{TEST_PROMPT_CANARY}'"],
    )
