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
import logging
import uuid
from abc import ABC
from datetime import UTC, datetime
from typing import Any, Callable, TypeVar

from alltrue.control.batch import BatchRuleProcessor
from alltrue.control.chat import RuleProcessor
from alltrue.http import HttpStatus
from alltrue.utils.config import get_value
from pydantic import BaseModel, ConfigDict

from alltrue.event.loop import ThreadExecutor
from alltrue.guardrails import _msg_key

I = TypeVar("I")
O = TypeVar("O")


class GuardrailsException(Exception):
    message: str

    def __init__(self, message: str, *args, **kwargs):
        self.message = message
        super().__init__(*args, **kwargs)


class GuardableMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str
    role: str = "user"

    @classmethod
    def parse(cls, content: Any, role: str | None = None) -> "GuardableMessage":
        match content:
            case _guardable if type(content).__name__ == "GuardableMessage":
                return _guardable
            case _model if issubclass(type(_model), BaseModel):
                return GuardableMessage(**_model.model_dump())
            case _dict if isinstance(_dict, dict):
                return GuardableMessage(**_dict)
            case others:
                return GuardableMessage(
                    **{
                        "content": str(others),
                        **({"role": role} if role is not None else {}),
                    }
                )

    @classmethod
    def parse_all(cls, contents: list[Any]) -> list["GuardableMessage"]:
        return [cls.parse(msg) for msg in contents]

    @classmethod
    def hash(cls, contents: list[Any]) -> tuple[str, list["GuardableMessage"]]:
        parsed = cls.parse_all(contents)
        return _msg_key([msg.content for msg in parsed]), parsed


Guardable = GuardableMessage | dict[str, str] | str


class _GuardTrailHooks(BaseModel):
    before: Callable[[I], str] = json.dumps
    after: Callable[[str], I] = json.loads


class ChatGuardian(ABC):
    """
    An abstract class of generic LLM chat message guardian.
    Two async methods provided by this class for input/output message protections and the users can determine whether to wait on the result.
    """

    def __init__(
        self,
        alltrue_api_url: str | None = None,
        alltrue_api_key: str | None = None,
        alltrue_customer_id: str | None = None,
        alltrue_endpoint_identifier: str | None = None,
        logging_level: int | str = logging.INFO,
        _llm_api_provider: str = "any",
        **kwargs,
    ):
        """
        :param alltrue_api_url: Alltrue API base URL, could as well be loaded via envar <ALLTRUE_API_URL>. Default to https://prod.alltrue.com
        :param alltrue_api_key: Alltrue API key, could as well be loaded via envar <ALLTRUE_API_KEY>.
        :param alltrue_customer_id: the customer ID registered in Alltrue API, could as well be loaded via envar <ALLTRUE_CUSTOMER_ID>
        :param alltrue_endpoint_identifier: the endpoint identifier defined in Alltrue API for LLM validation/observability could as well be loaded via envar <ALLTRUE_ENDPOINT_IDENTIFIER>
        :param logging_level: logging level to use
        """
        self._log = logging.getLogger("alltrue.guardrails")
        self._log.setLevel(logging_level)
        self._endpoint_identifier = alltrue_endpoint_identifier or get_value(
            name="endpoint_identifier"
        )
        self._guard_processor = RuleProcessor(
            llm_api_provider=_llm_api_provider,
            customer_id=alltrue_customer_id,
            api_url=alltrue_api_url,
            api_key=alltrue_api_key,
        )
        self._prompt_hooks = _GuardTrailHooks()
        self._completion_hooks = _GuardTrailHooks()
        self._rid_cache: dict[str, str] = dict()

    def register_prompt_hooks(
        self, before: Callable[[I], str], after: Callable[[str], I]
    ) -> None:
        self._prompt_hooks = _GuardTrailHooks(before=before, after=after)

    def register_completion_hooks(
        self, before: Callable[[I], str], after: Callable[[str], I]
    ) -> None:
        self._completion_hooks = _GuardTrailHooks(before=before, after=after)

    def _cache_prompt(
        self,
        prompt_messages: list[Guardable],
        req_id: str = str(uuid.uuid4()),
    ) -> tuple[str, list[Guardable]]:
        (hash_key, prompts) = GuardableMessage.hash(prompt_messages)
        if len(self._rid_cache) >= 20:
            self._rid_cache.pop(next(iter(self._rid_cache)))
        self._rid_cache[hash_key] = req_id
        return req_id, prompts  # type: ignore

    def _pop_prompt(
        self, prompt_messages: list[Guardable]
    ) -> tuple[str, list[Guardable]]:
        (hash_key, prompts) = GuardableMessage.hash(prompt_messages)
        req_id = self._rid_cache.pop(hash_key, str(uuid.uuid4()))
        return req_id, prompts  # type: ignore

    async def guard_input(self, prompt_messages: list[Guardable]) -> list[Guardable]:
        """
        Validate the given prompt messages then return back the suggested ones, or GuardrailsException when critical violations detected.
        """
        (req_id, prompt) = self._cache_prompt(prompt_messages)
        processed_result = await self._guard_processor.process_request(
            body=self._prompt_hooks.before(prompt),
            request_id=req_id,
            headers=[
                ("Content-Type", "application/json"),
            ],
            endpoint_identifier=self._endpoint_identifier,
        )
        if processed_result is not None:
            if HttpStatus.is_unauthorized(processed_result.status_code):
                raise GuardrailsException(
                    message=processed_result.message or "Invalid messages"
                )
            (_, new_prompt) = self._cache_prompt(
                self._prompt_hooks.after(processed_result.new_body),
                req_id=req_id,
            )
            return new_prompt
        else:
            return prompt

    async def guard_output(
        self, prompt_messages: list[Guardable], completion_messages: list[Guardable]
    ) -> list[Guardable]:
        """
        Validate the given completion messages alongside the input, then return back the suggested ones, or GuardrailsException when critical violations detected.
        """
        (req_id, prompt) = self._pop_prompt(prompt_messages)
        processed_result = await self._guard_processor.process_response(
            body=self._completion_hooks.before(completion_messages),
            original_request_input=self._prompt_hooks.before(prompt),
            request_id=req_id,
            request_headers=[
                ("Content-Type", "application/json"),
            ],
            endpoint_identifier=self._endpoint_identifier,
        )
        if processed_result is not None:
            if processed_result.status_code >= 400:
                raise GuardrailsException(
                    message=processed_result.message or "Invalid messages"
                )
        return (
            self._completion_hooks.after(processed_result.new_body)
            if processed_result
            else completion_messages
        )


class ChatGuardrails(ChatGuardian):
    """
    Input/output message guard/observation for LLM API calls.

    Two types of action provided by this class --
    * guard_input/guard_output: blocking
    """

    def __init__(
        self,
        alltrue_api_url: str | None = None,
        alltrue_api_key: str | None = None,
        alltrue_customer_id: str | None = None,
        alltrue_endpoint_identifier: str | None = None,
        logging_level: int | str = logging.INFO,
        batch_size: int = 0,
        queue_time: float = 1.0,
        **kwargs,
    ):
        super().__init__(
            alltrue_api_url=alltrue_api_url,
            alltrue_api_key=alltrue_api_key,
            alltrue_customer_id=alltrue_customer_id,
            alltrue_endpoint_identifier=alltrue_endpoint_identifier,
            logging_level=logging_level,
            _llm_api_provider="openai",
            **kwargs,
        )
        self.register_prompt_hooks(
            before=lambda messages: json.dumps(
                {
                    "model": "gpt-4o",
                    "messages": [msg.model_dump() for msg in messages],
                }
            ),
            after=lambda prompt: GuardableMessage.parse_all(
                json.loads(prompt).get("messages", [])
            ),
        )
        self.register_completion_hooks(
            before=lambda messages: json.dumps(
                {
                    "id": str(uuid.uuid4()),
                    "created": int(datetime.now(UTC).timestamp()),
                    "object": "chat.completion",
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "message": GuardableMessage.parse(msg).model_dump(),
                            "index": i,
                            "finish_reason": "stop",
                        }
                        for i, msg in enumerate(messages)
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "completion_tokens_details": {},
                    },
                }
            ),
            after=lambda completion: [
                GuardableMessage.parse(
                    content=choice.get("message", {}), role="assistant"
                )
                for choice in json.loads(completion).get("choices", [])
            ],
        )

        if batch_size == 0 or queue_time == 0:
            # either way, batcher will be disabled
            self._observing_processor = self._guard_processor
            self._batch_control = None
        else:
            self._log.info("Traces will be processed in batches")
            self._observing_processor = BatchRuleProcessor.clone(
                original=self._guard_processor,
                batch_size=batch_size,
                queue_time=queue_time,
            )
            self._batch_control = {"batch_size": batch_size, "queue_time": queue_time}
        try:
            if asyncio.get_running_loop() is not None:
                self._executor = asyncio
        except RuntimeError:
            self._log.info("No running loop.")
            self._executor = ThreadExecutor()  # type: ignore

    def observe_input(self, prompt_messages: list[Guardable]) -> None:
        """
        Observe the input in the background
        """
        (req_id, prompt) = self._cache_prompt(prompt_messages)
        self._executor.run(
            self._observing_processor.process_request(
                body=self._prompt_hooks.before(prompt),
                request_id=req_id,
                headers=[
                    ("Content-Type", "application/json"),
                ],
                endpoint_identifier=self._endpoint_identifier,
            )
        )

    def observe_output(
        self,
        prompt_messages: list[Guardable],
        completion_messages: list[Guardable],
    ) -> None:
        """
        Observe the output in the background
        """
        (req_id, prompt) = self._pop_prompt(prompt_messages)
        self._executor.run(
            self._observing_processor.process_response(
                body=self._completion_hooks.before(completion_messages),
                original_request_input=self._prompt_hooks.before(prompt),
                request_id=req_id,
                request_headers=[
                    ("Content-Type", "application/json"),
                ],
                endpoint_identifier=self._endpoint_identifier,
            )
        )

    def flush(self, timeout: float = 1.0):
        """
        Flush whatever currently queued in batcher
        """
        self._rid_cache.clear()
        self._executor.run(
            self._observing_processor.close(timeout=timeout),
        )
        # restart batcher
        if self._batch_control:
            self._observing_processor = BatchRuleProcessor.clone(
                original=self._observing_processor,
            )
