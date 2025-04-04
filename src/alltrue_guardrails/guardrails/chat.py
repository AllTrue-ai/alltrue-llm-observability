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
from typing import Any, Callable

from alltrue_guardrails.control.batch import BatchRuleProcessor
from alltrue_guardrails.control.chat import RuleProcessor
from alltrue_guardrails.http import HttpStatus
from alltrue_guardrails.utils.config import get_value
from pydantic import BaseModel, ConfigDict

from alltrue_guardrails.event.loop import ThreadExecutor
from alltrue_guardrails.guardrails import _msg_key


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


class _GuardTrailHooks(BaseModel):
    before: Callable[[list[GuardableMessage]], str] = json.dumps
    after: Callable[[str], list[GuardableMessage]] = json.loads


GuardableItems = list[GuardableMessage] | list[dict[str, str]] | list[str]


class ChatGuardian(ABC):
    """
    An abstract class of generic LLM chat message guardian.
    Two async methods provided by this class for input/output message protections and the users can determine whether to wait on the result.
    """

    def __init__(
        self,
        alltrue_api_url: str | None = None,
        alltrue_api_key: str | None = None,
        alltrue_endpoint_identifier: str | None = None,
        logging_level: int | str = logging.INFO,
        _llm_api_provider: str = "any",
        _keep_alive: bool | None = None,
        _timeout: float | None = None,
        _retries: int | None = None,
        **kwargs,
    ):
        """
        :param alltrue_api_url: Alltrue API base URL, could as well be loaded via envar <ALLTRUE_API_URL>. Default to https://api.prod.alltrue-be.com
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
            api_url=alltrue_api_url,
            api_key=alltrue_api_key,
            logging_level=logging_level,
            _keep_alive=_keep_alive,
            _timeout=_timeout,
            _retries=_retries,
        )
        self._prompt_hooks = _GuardTrailHooks()
        self._completion_hooks = _GuardTrailHooks()
        self._id_cache: dict[str, str] = dict()

    def register_prompt_hooks(
        self,
        before: Callable[[list[GuardableMessage]], str],
        after: Callable[[str], list[GuardableMessage]],
    ) -> None:
        self._prompt_hooks = _GuardTrailHooks(before=before, after=after)

    def register_completion_hooks(
        self,
        before: Callable[[list[GuardableMessage]], str],
        after: Callable[[str], list[GuardableMessage]],
    ) -> None:
        self._completion_hooks = _GuardTrailHooks(before=before, after=after)

    def _cache_prompt(
        self,
        prompt_messages: GuardableItems,
        req_id: str = str(uuid.uuid4()),
    ) -> tuple[str, list[GuardableMessage]]:
        (hash_key, prompts) = GuardableMessage.hash(prompt_messages)
        if len(self._id_cache) >= 20:
            self._id_cache.pop(next(iter(self._id_cache)))
        self._id_cache[hash_key] = req_id
        return req_id, prompts  # type: ignore

    def _pop_prompt(
        self, prompt_messages: GuardableItems
    ) -> tuple[str, list[GuardableMessage]]:
        (hash_key, prompts) = GuardableMessage.hash(prompt_messages)
        req_id = self._id_cache.pop(hash_key, str(uuid.uuid4()))
        return req_id, prompts  # type: ignore

    async def guard_input(
        self,
        prompt_messages: GuardableItems,
        chat_id: uuid.UUID | None = None,
        quick_response: bool = True,
    ) -> GuardableItems:
        """
        Validate the given prompt messages then return back the suggested ones, or GuardrailsException when critical violations detected.

        :param prompt_messages: list of prompt messages
        :param chat_id: optional uuid to be used for traceability
        :param quick_response: whether to return as soon as when the given messages are considered valid
        """

        (req_id, prompt) = self._cache_prompt(
            prompt_messages=prompt_messages,
            **({} if chat_id is None else {"req_id": str(chat_id)}),
        )
        if all([len(msg.content.strip()) == 0 for msg in prompt]):
            # skip on empty request
            return prompt_messages

        processed = await self._guard_processor.process_prompt(
            request_id=req_id,
            endpoint_identifier=self._endpoint_identifier,
            prompt_input=self._prompt_hooks.before(prompt),
            validation="usage",
            quick_response=quick_response,
        )
        if processed is not None:
            if HttpStatus.is_unauthorized(processed.status_code):
                raise GuardrailsException(
                    message=processed.message or "Invalid messages"
                )
            (_, new_prompt) = self._cache_prompt(
                self._prompt_hooks.after(processed.content),
                req_id=req_id,
            )

            match prompt_messages[0]:
                case r if isinstance(r, str):
                    return [m.content for m in new_prompt]
                case r if isinstance(r, dict):
                    return [m.model_dump() for m in new_prompt]
                case _:
                    return new_prompt
        else:
            return prompt_messages

    async def guard_output(
        self,
        prompt_messages: GuardableItems,
        completion_messages: GuardableItems,
        chat_id: uuid.UUID | None = None,
        quick_response: bool = True,
    ) -> GuardableItems:
        """
        Validate the given completion messages alongside the input, then return back the suggested ones, or GuardrailsException when critical violations detected.

        :param prompt_messages: list of original prompt messages
        :param completion_messages: list of completion messages to be verified
        :param chat_id: optional uuid to be used for traceability
        :param quick_response: whether to return as soon as when the given messages are considered valid
        """
        completion = GuardableMessage.parse_all(completion_messages)
        if all([len(msg.content.strip()) == 0 for msg in completion]):
            # skip on empty request
            return completion_messages

        if chat_id is None:
            (req_id, prompt) = self._pop_prompt(prompt_messages)
        else:
            req_id = str(chat_id)
            prompt = GuardableMessage.parse_all(prompt_messages)

        processed_result = await self._guard_processor.process_prompt(
            request_id=req_id,
            endpoint_identifier=self._endpoint_identifier,
            prompt_input=self._prompt_hooks.before(prompt),
            prompt_output=self._completion_hooks.before(completion),
            validation="usage",
            quick_response=quick_response,
        )
        if processed_result is not None:
            if HttpStatus.is_unauthorized(processed_result.status_code):
                raise GuardrailsException(
                    message=processed_result.message or "Invalid messages"
                )

            new_completion = self._completion_hooks.after(processed_result.content)
            match completion_messages[0]:
                case r if isinstance(r, str):
                    return [m.content for m in new_completion]
                case r if isinstance(r, dict):
                    return [m.model_dump() for m in new_completion]
                case _:
                    return new_completion
        return completion_messages

    async def trace(self, chat_id: uuid.UUID) -> dict | None:
        """
        Return the trace of the particular chat process, or None if no match.
        """
        result = await self._guard_processor.get_processed_traces(
            request_id=str(chat_id)
        )
        if result is not None and HttpStatus.is_success(result.status_code):
            return json.loads(result.content)
        return None


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
        alltrue_endpoint_identifier: str | None = None,
        logging_level: int | str = logging.INFO,
        _batch_size: int = 0,
        _queue_time: float = 1.0,
        _loop: asyncio.AbstractEventLoop | None = None,
        **kwargs,
    ):
        super().__init__(
            alltrue_api_url=alltrue_api_url,
            alltrue_api_key=alltrue_api_key,
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
                            "message": msg.model_dump(),
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

        if _batch_size == 0 or _queue_time == 0:
            # either way, batcher will be disabled
            self._observing_processor = self._guard_processor
            self._batch_control = None
        else:
            self._log.info("Batching enabled")
            self._observing_processor = BatchRuleProcessor.clone(
                original=self._guard_processor,
                batch_size=_batch_size,
                queue_time=_queue_time,
            )
            self._batch_control = {"batch_size": _batch_size, "queue_time": _queue_time}
        try:
            if _loop is None:
                if asyncio.get_running_loop() is not None:
                    self._executor = asyncio
            else:
                self._executor = ThreadExecutor(loop=_loop)  # type: ignore
        except RuntimeError:
            self._log.info("No running loop, thread executor will be adapted")
            self._executor = ThreadExecutor()  # type: ignore

    def observe_input(
        self,
        prompt_messages: GuardableItems,
        chat_id: uuid.UUID | None = None,
    ) -> None:
        """
        Observe the prompt messages in the background

        :param prompt_messages: the prompt messages to be observed
        :param chat_id: optional chat id for later traceability
        """
        (req_id, prompt) = self._cache_prompt(
            prompt_messages=prompt_messages,
            **({} if chat_id is None else {"req_id": str(chat_id)}),
        )
        if all([len(msg.content.strip()) == 0 for msg in prompt]):
            # skip on empty request
            self._log.debug("skipped observing input")
            return

        self._log.debug(f"observing input: {req_id}")
        self._executor.ensure_future(
            self._observing_processor.process_prompt(
                request_id=req_id,
                endpoint_identifier=self._endpoint_identifier,
                prompt_input=self._prompt_hooks.before(prompt),
                validation="connection",
                quick_response=False,
            )
        )

    def observe_output(
        self,
        prompt_messages: GuardableItems,
        completion_messages: GuardableItems,
        chat_id: uuid.UUID | None = None,
    ) -> None:
        """
        Observe the completion messages in the background

        :param prompt_messages: the original prompt messages
        :param completion_messages: the completion messages to be observed
        :param chat_id: optional chat id for later traceability
        """
        completion = GuardableMessage.parse_all(completion_messages)
        if all([len(msg.content.strip()) == 0 for msg in completion]):
            # skip on empty request
            self._log.debug("skipped observing output")
            return

        if chat_id is None:
            (req_id, prompt) = self._pop_prompt(prompt_messages)
        else:
            req_id = str(chat_id)
            prompt = GuardableMessage.parse_all(prompt_messages)

        self._log.debug(f"observing output: {req_id}")
        self._executor.ensure_future(
            self._observing_processor.process_prompt(
                request_id=req_id,
                endpoint_identifier=self._endpoint_identifier,
                prompt_input=self._prompt_hooks.before(prompt),
                prompt_output=self._completion_hooks.before(completion),
                validation="connection",
                quick_response=False,
            )
        )

    def flush(self, timeout: float = 1.0):
        """
        Flush whatever currently queued in batcher
        """
        self._id_cache.clear()
        self._executor.run(
            self._observing_processor.close(timeout=timeout),
        )
        # restart batcher
        if self._batch_control:
            self._observing_processor = BatchRuleProcessor.clone(
                original=self._observing_processor,
                **self._batch_control,  # type: ignore
            )
