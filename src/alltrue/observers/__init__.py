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
import logging
import uuid
from importlib import import_module
from typing import Any, Callable, Coroutine

from alltrue.control.chat import ProcessResult, RuleProcessor
from alltrue.utils.config import get_value
from alltrue.utils.path import EndpointInfo
from typing_extensions import Literal, NamedTuple
from wrapt import ObjectProxy, wrap_function_wrapper

from alltrue.event.loop import ThreadExecutor


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
        alltrue_customer_id: str | None = None,
        alltrue_endpoint_identifier: str | None = None,
        llm_api_provider: str = "any",
        llm_api_url: str | None = None,
        llm_api_path: str = "",
        logging_level: int | str = logging.INFO,
        blocking: bool = False,
    ):
        """
        :param alltrue_api_url: Alltrue API URL, loading from config `CONFIG_API_URL` if not specified.
        :param alltrue_api_key: API key for Alltrue API authentication, loading from config `CONFIG_API_KEY` if not specified.
        :param alltrue_customer_id: Alltrue API customer ID, loading from config `CONFIG_CUSTOMER_ID` if not specified.
        :param alltrue_endpoint_identifier: default endpoint identifier for later communicate with Alltrue APIs when specified.
        :param llm_api_provider: LLM API provider
        :param llm_api_url: LLM API base URL, giving none to use the default one from LLM API provider when available.
        :param llm_api_path: LLM API endpoint path
        :param logging_level: logging level, default to INFO
        :param blocking: whether to block the execution while any abnormality observed
        """
        self._log = logging.getLogger("alltrue.observer")
        self._log.setLevel(logging_level)

        self._rule_processor = RuleProcessor(
            llm_api_provider=llm_api_provider,
            customer_id=alltrue_customer_id,
            api_url=alltrue_api_url,
            api_key=alltrue_api_key,
            _connection_keep_alive="none",
        )
        if not alltrue_endpoint_identifier:
            alltrue_endpoint_identifier = get_value("endpoint_identifier")
        self._default_endpoint_info = EndpointInfo(
            base_url=llm_api_url,
            endpoint_identifier=alltrue_endpoint_identifier,
            proxy_type=llm_api_provider,
            path=llm_api_path,
        )
        self._llm_api_url = self._rule_processor.config.api_url
        self._observables: list[Observable] = []
        self._loop = ThreadExecutor()
        self._blocking = blocking

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
            self._log.info(f"[OBSERVER] {rid}: observing {rtype} in background...")
            self._loop.ensure_future(
                request_process,
                call_back=lambda task: self._log.info(
                    f"[OBSERVER] {rid}: {rtype} background execution {task.exception() or ('cancelled' if task.cancelled() else 'completed')}]"
                ),
            )
            return None

    def _patch_async_action(self):
        async def wrap_async_action(wrapped, instance, args, kwargs):
            rid = str(uuid.uuid4())
            call_args = ObservedArgs(args=args, kwargs=kwargs)
            request = self._before_input_process(instance, call_args)

            self._log.debug(f"[OBSERVER] {rid}: {request}")
            request_url = request.full_url
            request_body = request.payload

            self._log.debug(f"[OBSERVER] {rid}: observing input prompts...")
            request_process_result = await self._handle_request(
                rtype="input",
                rid=rid,
                request_process=self._rule_processor.process_request(
                    body=request_body,
                    request_id=rid,
                    url=request_url,
                    method="POST",
                    headers=request.params,
                    endpoint_identifier=request.endpoint.endpoint_identifier,
                    llm_api_provider=request.endpoint.proxy_type,
                ),
            )
            if request_process_result:
                (args, kwargs) = self._after_input_process(
                    request_process_result,
                    request,
                    instance,
                    call_args,
                )

            self._log.info(f"[OBSERVER] {rid}: forwarding prompts to API backend...")
            result = wrapped(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result

            self._log.debug(f"[OBSERVER] {rid}: observing output completions...")
            response_process_result = await self._handle_request(
                rtype="output",
                rid=rid,
                request_process=self._rule_processor.process_response(
                    body=self._before_output_process(
                        result, request, instance, call_args
                    ),
                    original_request_input=request_body,
                    request_id=rid,
                    url=request_url,
                    method="POST",
                    request_headers=request.params,
                    endpoint_identifier=request.endpoint.endpoint_identifier,
                    llm_api_provider=request.endpoint.proxy_type,
                ),
            )
            if response_process_result:
                return (
                    self._after_output_process(
                        response_process_result, request, instance, call_args
                    )
                    or result
                )

            return result

        return wrap_async_action

    def _patch_sync_action(self):
        patched = self._patch_async_action()

        def wrap_sync_action(wrapped, instance, args, kwargs):
            return asyncio.run(patched(wrapped, instance, args, kwargs))

        return wrap_sync_action

    def register(self):
        """
        Register this observer to all observable operations.
        """
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
