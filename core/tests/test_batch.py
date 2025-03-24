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
import json
import re
import time
import uuid

import httpx
import pytest
from alltrue_guardrails.control.batch import BatchRuleProcessor
from alltrue_guardrails.http import HttpStatus


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
@pytest.mark.asyncio
async def test_batch_input_process(httpx_mock):
    test_body = {
        "message": {
            "content": "content",
            "rule": "user",
        }
    }

    def _response(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/batch/process-input/any"):
            payload = json.loads(request.content)
            assert "requests" in payload
            assert (
                json.loads(payload["requests"][0]["original_request_body"])["message"][
                    "content"
                ]
                == test_body["message"]["content"]
            )

            return httpx.Response(
                status_code=HttpStatus.OK,
                json={"time": time.time()},
            )
        elif request.url.path.endswith("jwt-token"):
            return httpx.Response(
                status_code=HttpStatus.OK,
                json={"access_token": str(time.time())},
            )
        return httpx.Response(404)

    httpx_mock.add_callback(_response)

    processor = BatchRuleProcessor(
        api_url="http://localhost:8080",
        api_key="dummy-api-key",
        customer_id="dummy-customer-id",
        llm_api_provider="any",
        batch_size=3,
    )
    tasks = []
    for i in range(10):  # the batches should be in 3, 3, 3, 1 four times
        t = asyncio.ensure_future(
            processor.process_request(
                body=json.dumps(test_body),
                request_id=str(uuid.uuid4()),
                endpoint_identifier="dummy-endpoint-identifier",
                url="https://httpbin.org/get/abc/123",
            )
        )
        tasks.append(t)
    for t in tasks:
        await t
        res = t.result()
        assert res.status_code == HttpStatus.OK
        assert (
            json.loads(res.new_body)["message"]["content"]
            == test_body["message"]["content"]
        )

    assert len(httpx_mock.get_requests()) == 5

    result = await processor.process_response(
        body=json.dumps({}),
        original_request_input=json.dumps(test_body),
        request_id=str(uuid.uuid4()),
        endpoint_identifier="dummy-endpoint-identifier",
        url="https://httpbin.org/get/abc/123",
    )
    assert result.status_code == HttpStatus.OK
    await asyncio.sleep(0.75)
    assert httpx_mock.get_request(url=re.compile(r".*/batch/process-output/any"))

    # clean up
    await processor.close()
