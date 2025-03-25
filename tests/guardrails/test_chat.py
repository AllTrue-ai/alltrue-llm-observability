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
import logging
import os
import time
import uuid

import httpx
import pytest

from alltrue_guardrails.guardrails.chat import ChatGuardrails
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
async def guardrails(openai_test_ports, test_endpoint_identifier):
    (api_port, proxy_port) = openai_test_ports
    _guardrails = ChatGuardrails(
        alltrue_api_url=f"http://localhost:{api_port}",
        alltrue_api_key="dummy-app-key",
        alltrue_endpoint_identifier=test_endpoint_identifier,
        alltrue_customer_id="customer-id",
        logging_level=logging.DEBUG,
        _loop=asyncio.get_running_loop(),
        _batch_size=4,
        _queue_time=1,
        _keep_alive=False,
    )
    assert await _guardrails.validate() == True
    yield _guardrails
    _guardrails.flush(5)
    await asyncio.sleep(2)


@pytest.fixture(scope="module")
def openai_api_key():
    return "dummy-api-key"


@pytest.mark.skip_on_remote
@pytest.mark.asyncio
async def test_empty_messages(guardrails):
    messages = ["", ""]
    assert messages == await guardrails.guard_input(messages)
    assert messages == await guardrails.guard_output(messages, messages)


@pytest.mark.skip_on_remote
@pytest.mark.asyncio
async def test_self_generated_chat_id(guardrails):
    chat_id = uuid.uuid4()
    messages = ["randon_string"]
    await guardrails.guard_input(messages, chat_id=chat_id)

    assert str(chat_id) in guardrails._id_cache.values()


@pytest.mark.skip_on_remote
@pytest.mark.asyncio
async def test_message_guard(
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
            "messages": [{"content": msg, "role": "user"} for msg in guarded_input],
        },
    )

    # call guard_output to process the completion messages
    guarded_output = await guardrails.guard_output(
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


@pytest.mark.skip_on_remote
@pytest.mark.asyncio
def test_message_observing(
    openai_api_key,
    openai_test_ports: tuple[int, int],
    test_endpoint_identifier,
    guardrails,
):
    for i in range(10):
        messages = [f"reject '{TEST_PROMPT_CANARY}"]
        # call guard_input to observe input only, no exception should be thrown
        guardrails.observe_input(messages)

        # call observe_output to observe output only, no exception should be thrown
        guardrails.observe_output(
            messages,
            [f"reject '{TEST_PROMPT_CANARY}'"],
        )
        time.sleep(0.1 * i)
