#
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

import datetime
import json
import logging

from mitmproxy import http

logger = logging.getLogger("mock:openai")

MOCK_REPLIES = {
    "Hamlet": lambda txt: 'William Shakespeare wrote the play "Hamlet".',
    "print the string": lambda txt: txt.replace("print the string ", ""),
    "return the string": lambda txt: txt.replace("return the string ", ""),
}


class MockLlmOpenAI:
    """
    Hijack requests to not actually pass to OpenAI
    """

    async def request(self, flow: http.HTTPFlow) -> None:
        if flow.request.headers.get("x-alltrue-test-bypass", None) is not None:
            logger.info("    [MOCK_OPENAI] Bypassing OpenAI simulation")
            return

        keyword = next(
            filter(lambda k: k in flow.request.text, MOCK_REPLIES.keys()), None
        )
        if keyword:
            logger.info(f"    [MOCK_OPENAI] asking about {keyword}")
            logger.info(f"    [MOCK_OPENAI] {flow.request.json()}")
            flow.response = http.Response.make(
                status_code=200,
                headers={
                    "Content-Type": "application/json",
                    "openai-organization": "alltrue-ai",
                    "X-Answered-By": "mock:openai",
                },
                content=json.dumps(
                    {
                        "id": "chatcmpl-mocked-random-id",
                        "object": "chat.completion",
                        "created": int(datetime.datetime.now(datetime.UTC).timestamp()),
                        "model": "gpt-3.5-turbo-0125",
                        "choices": [
                            {
                                "index": i,
                                "message": {
                                    "role": "assistant",
                                    "content": MOCK_REPLIES[keyword](
                                        msg.get("content", "")
                                    ),
                                },
                                "finish_reason": "stop",
                            }
                            for i, msg in enumerate(
                                flow.request.json().get("messages", [])
                            )
                        ],
                        "usage": {
                            "prompt_tokens": 15,
                            "completion_tokens": 9,
                            "total_tokens": 24,
                            "prompt_tokens_details": {
                                "cached_tokens": 0,
                                "audio_tokens": 0,
                            },
                            "completion_tokens_details": {
                                "reasoning_tokens": 0,
                                "audio_tokens": 0,
                                "accepted_prediction_tokens": 0,
                                "rejected_prediction_tokens": 0,
                            },
                        },
                    }
                ),
            )
        else:
            logger.info(f"    [MOCK_OPENAI] Unknown OpenAI operation: {flow.response}")
            flow.response = http.Response.make(
                403,
                headers={
                    "Content-Type": "application/json",
                    "X-Answered-By": "mock:openai",
                },
                content=json.dumps(
                    {
                        "Reason": "unexpected request",
                    }
                ),
            )


addons = [MockLlmOpenAI()]
