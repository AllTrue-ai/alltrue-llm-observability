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
import uuid
from importlib import import_module
from typing import Any, Callable, Coroutine

from alltrue_guardrails.control.batch import BatchRuleProcessor
from alltrue_guardrails.control.chat import ProcessResult, RuleProcessor
from alltrue_guardrails.utils.config import AlltrueConfig, get_value
from alltrue_guardrails.utils.path import EndpointInfo
from typing_extensions import Literal, NamedTuple
from wrapt import ObjectProxy, wrap_function_wrapper

from alltrue_guardrails.event.loop import ThreadExecutor


def unwrap(obj: object, attr: str):
    """Given a function that was wrapped by wrapt.wrap_function_wrapper, unwrap it

    The object containing the function to unwrap may be passed as dotted module path string.

    Args:
        obj: Object that holds a reference to the wrapped function or dotted import path as string
        attr (str): Name of the wrapped function
    """
    if isinstance(obj, str):
        try:
            module_path, class_name = obj.rsplit(".", 1)
        except ValueError as exc:
            raise ImportError(f"Cannot parse '{obj}' as dotted import path") from exc
        module = import_module(module_path)
        try:
            obj = getattr(module, class_name)
        except AttributeError as exc:
            raise ImportError(f"Cannot import '{class_name}' from '{module}'") from exc

    func = getattr(obj, attr, None)
    if func and isinstance(func, ObjectProxy) and hasattr(func, "__wrapped__"):
        setattr(obj, attr, func.__wrapped__)


class Observable(NamedTuple):
    module_name: str
    class_name: str
    func_name: str
    is_async: bool


EndpointParams = list[tuple[str, str]]
FunctionArgs = tuple[Any, ...]
FunctionKwargs = dict[str, Any]
ObservedFunction = Callable[[FunctionArgs], FunctionKwargs]
ObservedInstance = Any


class EndpointRequest(NamedTuple):
    url: str
    endpoint: EndpointInfo
    params: EndpointParams
    payload: str

    @property
    def full_url(self) -> str:
        return f"{self.url.removesuffix('/')}/{self.endpoint.path.strip().removeprefix('/')}"


class ObservedArgs(NamedTuple):
    args: FunctionArgs
    kwargs: FunctionKwargs


class BaseObserver:
    def __init__(
        self,
        alltrue_api_url: str | None = None,
        alltrue_api_key: str | None = None,
        alltrue_endpoint_identifier: str | None = None,
        llm_api_provider: str = "any",
        llm_api_url: str | None = None,
        llm_api_path: str = "",
        logging_level: int | str = logging.INFO,
        blocking: bool = False,
        _batch_size: int = 0,
        _queue_time: float = 1.0,
        _keep_alive: bool | None = None,
        _timeout: float | None = None,
        _retries: int | None = None,
    ):
        """
        :param alltrue_api_url: Alltrue API URL, loading from config `CONFIG_API_URL` if not specified.
        :param alltrue_api_key: API key for Alltrue API authentication, loading from config `CONFIG_API_KEY` if not specified.
        :param alltrue_endpoint_identifier: default endpoint identifier for later communicate with Alltrue APIs when specified.
        :param llm_api_provider: LLM API provider
        :param llm_api_url: LLM API base URL, giving none to use the default one from LLM API provider when available.
        :param llm_api_path: LLM API endpoint path
        :param logging_level: logging level, default to INFO
        :param blocking: whether to block the execution while any abnormality observed
        """
        self._log = logging.getLogger("alltrue.observer")
        self._log.setLevel(logging_level)

        self._config = AlltrueConfig(
            api_url=alltrue_api_url,
            api_key=alltrue_api_key,
            llm_api_provider=llm_api_provider,
        )
        self._rule_processor = None
        self._api_control = {
            "_keep_alive": _keep_alive,
            "_timeout": _timeout,
            "_retries": _retries,
        }
        if blocking or _batch_size == 0 or _queue_time == 0:
            self._batch_control = None
        else:
            self._batch_control = {
                "queue_time": _queue_time,
                "batch_size": _batch_size,
            }
        if not alltrue_endpoint_identifier:
            alltrue_endpoint_identifier = get_value("endpoint_identifier")
        self._default_endpoint_info = EndpointInfo(
            base_url=llm_api_url,
            endpoint_identifier=alltrue_endpoint_identifier,
            proxy_type=llm_api_provider,
            path=llm_api_path,
        )
        self._observables: list[Observable] = []
        self._blocking = blocking

        try:
            if asyncio.get_running_loop() is not None:
                self._executor = asyncio
        except RuntimeError:
            self._log.info("No running loop, thread executor will be adapted")
            self._executor = ThreadExecutor()  # type: ignore

    def _resolve_endpoint_info(self, **kwargs) -> EndpointInfo:
        """
        Get an endpoint info with the combination of default and updated settings
        """
        return self._default_endpoint_info.model_copy().merge(
            EndpointInfo.parse_from_headers(kwargs)
        )

    def _before_output_process(
        self,
        completion: Any,
        request: EndpointRequest,
        instance: ObservedInstance,
        call_args: ObservedArgs,
    ) -> str:
        raise NotImplementedError()

    def _after_output_process(
        self,
        response: ProcessResult,
        request: EndpointRequest,
        instance: ObservedInstance,
        call_args: ObservedArgs,
    ):
        """
        Converted a processed response to observable called result
        """
        raise NotImplementedError()

    def _before_input_process(
        self,
        instance: ObservedInstance,
        call_args: ObservedArgs,
    ) -> EndpointRequest:
        """
        Convert a call on observable to an endpoint request
        """
        raise NotImplementedError()

    def _after_input_process(
        self,
        result: ProcessResult,
        request: EndpointRequest,
        instance: ObservedInstance,
        call_args: ObservedArgs,
    ) -> ObservedArgs:
        raise NotImplementedError()

    async def _handle_request(
        self,
        rtype: Literal["input", "output"],
        rid: str,
        request_process: Coroutine[Any, Any, ProcessResult | None],
    ) -> ProcessResult | None:
        if self._blocking:
            return await request_process
        else:
            self._executor.ensure_future(  # type: ignore
                request_process,
            )
            self._log.info(f"{rtype}: {rid} request handled in background")
            return None

    def _patch_async_action(self):
        async def wrap_async_action(wrapped, instance, args, kwargs):
            rid = str(uuid.uuid4())
            call_args = ObservedArgs(args=args, kwargs=kwargs)
            request = self._before_input_process(instance, call_args)
            request_url = request.full_url
            request_body = request.payload

            self._log.debug(f"{rid}: observed")
            request_process_result = await self._handle_request(
                rtype="input",
                rid=rid,
                request_process=self._rule_processor.process_prompt(
                    request_id=rid,
                    prompt_input=request_body,
                    endpoint_identifier=request.endpoint.endpoint_identifier,
                    llm_api_provider=request.endpoint.proxy_type,
                    validation="usage" if self._blocking else "connection",
                    url=request_url,
                    method="POST",
                    headers=request.params,
                ),
            )
            if self._blocking and request_process_result:
                (args, kwargs) = self._after_input_process(
                    request_process_result,
                    request,
                    instance,
                    call_args,
                )

            self._log.debug(f"{rid}: forwarding to LLM API...")
            result = wrapped(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result

            self._log.debug(f"{rid}: LLM API response received")
            response_process_result = await self._handle_request(
                rtype="output",
                rid=rid,
                request_process=self._rule_processor.process_prompt(
                    request_id=rid,
                    prompt_output=self._before_output_process(
                        result, request, instance, call_args
                    ),
                    prompt_input=request_body,
                    endpoint_identifier=request.endpoint.endpoint_identifier,
                    llm_api_provider=request.endpoint.proxy_type,
                    validation="usage" if self._blocking else "connection",
                    url=request_url,
                    method="POST",
                    headers=request.params,
                ),
            )
            if self._blocking and response_process_result:
                return (
                    self._after_output_process(
                        response_process_result, request, instance, call_args
                    )
                    or result
                )
            self._log.debug(f"{rid}: observation completed")
            return result

        return wrap_async_action

    def _patch_sync_action(self):
        patched = self._patch_async_action()

        def wrap_sync_action(wrapped, instance, args, kwargs):
            return asyncio.run(patched(wrapped, instance, args, kwargs))

        return wrap_sync_action

    @property
    def is_blocking(self):
        return self._blocking

    def register(self):
        """
        Register this observer to all observable operations.
        """
        if self._batch_control is None:
            self._rule_processor = RuleProcessor(
                llm_api_provider=self._config.llm_api_provider,
                api_url=self._config.api_url,
                api_key=self._config.api_key,
                **self._api_control,
            )
        else:
            self._log.info("Batching enabled")
            self._rule_processor = BatchRuleProcessor(
                llm_api_provider=self._config.llm_api_provider,
                api_url=self._config.api_url,
                api_key=self._config.api_key,
                **self._api_control,
                **self._batch_control,
            )

        for observable in self._observables:
            wrap_function_wrapper(
                module=observable.module_name,
                name=f"{observable.class_name}.{observable.func_name}",
                wrapper=self._patch_async_action()
                if observable.is_async
                else self._patch_sync_action(),
            )

    def unregister(self):
        """
        Unregister this observer from all observing operations.
        """
        for observable in self._observables:
            unwrap(
                f"{observable.module_name}.{observable.class_name}",
                observable.func_name,
            )
        self._executor.run(self._rule_processor.close(timeout=1))
