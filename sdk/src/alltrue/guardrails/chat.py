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
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Coroutine, Generic, TypeVar

from alltrue.control.chat import RuleProcessor
from alltrue.event.loop import ThreadExecutor
from alltrue.guardrails import _msg_key
from alltrue.utils.config import get_value
from pydantic import BaseModel

_REQ_PROCESSOR_CFG = "x-alltrue-llm-request-processor"


I = TypeVar("I")
O = TypeVar("O")


class GuardrailsException(Exception):
    message: str

    def __init__(self, message: str, *args, **kwargs):
        self.message = message
        super().__init__(*args, **kwargs)


class _GuardedPrompt(BaseModel, Generic[I]):
    req_id: str
    prompt: I
    completion: Callable[[O], Coroutine[Any, Any, O]]

    @classmethod
    def init(
        cls,
        req_id: str,
        prompt: I,
        _callable: Callable[[str, I, O], Coroutine[Any, Any, O]],
    ) -> "_GuardedPrompt":
        async def _completion(c: O) -> O:
            return await _callable(req_id, prompt, c)

        return _GuardedPrompt(
            req_id=req_id,
            prompt=prompt,
            completion=_completion,
        )


class _GuardTrailHooks(BaseModel):
    before: Callable[[I], str] = json.dumps
    after: Callable[[str], I] = json.loads


class ChatGuardrails:
    def __init__(
        self,
        input_query: str | None = None,
        output_query: str | None = None,
        alltrue_api_url: str | None = None,
        alltrue_api_key: str | None = None,
        alltrue_customer_id: str | None = None,
        alltrue_endpoint_identifier: str | None = None,
        logging_level: int | str = logging.INFO,
        _api_provider: str = "any",
    ):
        self._log = logging.getLogger("alltrue.guardrails")
        self._log.setLevel(logging_level)

        self._processor_cfg = (
            {
                "processor-type": "jsonpath",
                "pre-input": input_query,
                "post-input": input_query,
                "pre-output": output_query,
                "post-output": output_query,
            }
            if input_query is not None and output_query is not None
            else None
        )
        self._endpoint_identifier = alltrue_endpoint_identifier or get_value(
            name="endpoint_identifier"
        )
        self._rule_processor = RuleProcessor(
            llm_api_provider=_api_provider,
            customer_id=alltrue_customer_id,
            api_url=alltrue_api_url,
            api_key=alltrue_api_key,
        )
        self._prompt_hooks = _GuardTrailHooks()
        self._completion_hooks = _GuardTrailHooks()

    def register_prompt_hooks(
        self, before: Callable[[I], str], after: Callable[[str], I]
    ) -> None:
        self._prompt_hooks = _GuardTrailHooks(before=before, after=after)

    def register_completion_hooks(
        self, before: Callable[[I], str], after: Callable[[str], I]
    ) -> None:
        self._completion_hooks = _GuardTrailHooks(before=before, after=after)

    async def guard_prompt(self, prompt: I) -> _GuardedPrompt[I]:
        req_id = str(uuid.uuid4())
        processed_result = await self._process_input(req_id=req_id, prompt=prompt)
        return _GuardedPrompt.init(
            req_id=req_id,
            prompt=processed_result if processed_result else prompt,
            _callable=self._process_output,
        )

    async def _process_input(self, req_id: str, prompt: I) -> I:
        processed_result = await self._rule_processor.process_request(
            body=self._prompt_hooks.before(prompt),
            request_id=req_id,
            headers=[
                ("Content-Type", "application/json"),
                *(
                    [(_REQ_PROCESSOR_CFG, json.dumps(self._processor_cfg))]
                    if self._processor_cfg
                    else []
                ),
            ],
            endpoint_identifier=self._endpoint_identifier,
        )
        if processed_result is not None:
            if processed_result.status_code >= 400:
                raise GuardrailsException(message=processed_result.message)
        return (
            self._prompt_hooks.after(processed_result.new_body)
            if processed_result
            else prompt
        )

    async def _process_output(self, req_id: str, prompt: I, completion: O) -> O:
        if asyncio.iscoroutine(completion):
            completion = await completion

        processed_result = await self._rule_processor.process_response(
            body=self._completion_hooks.before(completion),
            original_request_input=self._prompt_hooks.before(prompt),
            request_id=req_id,
            request_headers=[
                ("Content-Type", "application/json"),
                *(
                    [(_REQ_PROCESSOR_CFG, json.dumps(self._processor_cfg))]
                    if self._processor_cfg
                    else []
                ),
            ],
            endpoint_identifier=self._endpoint_identifier,
        )
        if processed_result is not None:
            if processed_result.status_code > 400:
                raise GuardrailsException(message=processed_result.message)
        return (
            self._completion_hooks.after(processed_result.new_body)
            if processed_result
            else completion
        )


class ChatGuardrailsLite:
    """
    Lite version of Guardrails for string messages
    """

    def __init__(self, **kwargs):
        self._guard = ChatGuardrails(
            **kwargs,
            input_query="messages[*].content",
            output_query="choices[*].message.content",
            _api_provider="openai",
        )
        self._guard.register_prompt_hooks(
            before=lambda list_of_msg: json.dumps(
                {
                    "model": "gpt-4o",
                    "messages": [
                        {"content": msg, "role": "user"} for msg in list_of_msg
                    ],
                }
            ),
            after=lambda text_of_msgs: [
                msg.get("content", "")
                for msg in json.loads(text_of_msgs).get("messages", [])
            ],
        )
        self._guard.register_completion_hooks(
            before=lambda list_of_msg: json.dumps(
                {
                    "id": str(uuid.uuid4()),
                    "created": int(datetime.now(UTC).timestamp()),
                    "object": "chat.completion",
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "message": {"content": msg, "role": "assistant"},
                            "index": i,
                            "finish_reason": "stop",
                        }
                        for i, msg in enumerate(list_of_msg)
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "completion_tokens_details": {},
                    },
                }
            ),
            after=lambda text_of_choices: [
                choice.get("message", {}).get("content", "")
                for choice in json.loads(text_of_choices).get("choices", [])
            ],
        )
        self._log = self._guard._log
        self._rid_cache = dict()
        self._loop = ThreadExecutor()

    async def guard_input(self, prompt_messages: list[str]) -> list[str]:
        """
        Guard the input messages by either returning new suggestions or throw out denied exception
        """
        req_id = str(uuid.uuid4())
        guarded_input = await self._guard._process_input(
            req_id=req_id, prompt=prompt_messages
        )
        self._rid_cache[_msg_key(prompt_messages)] = req_id
        return guarded_input

    def observe_input(self, prompt_messages: list[str]) -> None:
        """
        Observe the input in the background
        """
        self._loop.ensure_future(
            self.guard_input(prompt_messages),
        )

    async def guard_output(
        self, prompt_messages: list[str], completion_messages: list[str]
    ) -> list[str]:
        """
        Guard the output messages by either returning new suggestions or thrown out denied exception
        """
        req_id = self._rid_cache.pop(_msg_key(prompt_messages), str(uuid.uuid4()))
        guard_output = await self._guard._process_output(
            req_id=req_id, prompt=prompt_messages, completion=completion_messages
        )
        return guard_output

    def observe_output(
        self,
        prompt_messages: list[str],
        completion_messages: list[str],
    ) -> None:
        """
        Observe the output in the background
        """
        self._loop.ensure_future(
            self.guard_output(prompt_messages, completion_messages),
        )
