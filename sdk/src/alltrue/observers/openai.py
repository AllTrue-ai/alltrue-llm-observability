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
import json
from typing import Any, cast

import httpx
from alltrue.control.chat import ProcessResult
from alltrue.http import HttpStatus
from alltrue.observers import (
    BaseObserver,
    EndpointRequest,
    Observable,
    ObservedArgs,
    ObservedInstance,
)
from openai import PermissionDeniedError
from openai.types.chat import ChatCompletion
from typing_extensions import override


class OpenAIObserver(BaseObserver):
    """
    OpenAI Observer for chat completion operations.
    """

    @override
    def __init__(self, **kwargs):
        kwargs.pop("llm_api_type", None)
        kwargs.pop("llm_api_path", None)
        super().__init__(
            **kwargs,
            llm_api_provider="openai",
            llm_api_path="/chat/completions",
        )
        self._observables.extend(
            [
                Observable(
                    module_name="openai.resources.chat.completions",
                    class_name="Completions",
                    func_name="create",
                    is_async=False,
                ),
                Observable(
                    module_name="openai.resources.chat.completions",
                    class_name="AsyncCompletions",
                    func_name="create",
                    is_async=True,
                ),
            ]
        )

    def _before_output_process(
        self,
        completion: Any,
        request: EndpointRequest,
        instance: ObservedInstance,
        call_args: ObservedArgs,
    ) -> str:
        return cast(ChatCompletion, completion).model_dump_json()

    @override  # type: ignore
    def _after_output_process(
        self,
        response: ProcessResult,
        request: EndpointRequest,
        instance: ObservedInstance,
        call_args: ObservedArgs,
    ) -> ChatCompletion | None:
        if response.status_code == HttpStatus.OK and len(response.new_body or "") > 0:
            return ChatCompletion.model_validate(json.loads(response.new_body))
        elif response.status_code == HttpStatus.FORBIDDEN:
            raise PermissionDeniedError(
                message=response.message,
                response=httpx.Response(
                    status_code=response.status_code,
                    request=httpx.Request(
                        method="POST",
                        url=request.full_url,
                        headers=request.params,
                        content=request.payload,
                    ),
                ),
                body=response.new_body,
            )
        return None

    @override  # type: ignore
    def _before_input_process(
        self, instance: ObservedInstance, call_args: ObservedArgs
    ) -> EndpointRequest:
        openai_client = instance._client

        (args, kwargs) = call_args
        # merge all headers
        all_headers = openai_client.default_headers or {}
        all_headers.update(openai_client.auth_headers or {})
        all_headers.update(kwargs.get("extra_headers", {}))

        return EndpointRequest(
            url=str(openai_client.base_url) or "https://api.openai.com/v1"
            if openai_client.base_url != self._llm_api_url
            else self._llm_api_url,
            endpoint=self._resolve_endpoint_info(**all_headers),
            params=[
                (k, v)
                for k, v in filter(
                    lambda a: a[1], all_headers.items()
                )  # filter none values
            ],
            payload=json.dumps(
                {
                    "model": kwargs.get("model", None),
                    "messages": kwargs.get("messages", []),
                }
            ),
        )

    @override  # type: ignore
    def _after_input_process(
        self,
        result: ProcessResult,
        request: EndpointRequest,
        instance: ObservedInstance,
        call_args: ObservedArgs,
    ) -> ObservedArgs:
        (args, kwargs) = call_args
        if result.status_code == HttpStatus.OK and len(result.new_body or "") > 0:
            payload = json.loads(result.new_body)
            kwargs["model"] = payload.get("model", kwargs.get("model", None))
            kwargs["messages"] = payload.get("messages", kwargs.get("messages", []))
        elif result.status_code == HttpStatus.FORBIDDEN:
            raise PermissionDeniedError(
                message=result.message,
                response=httpx.Response(
                    status_code=result.status_code,
                    request=httpx.Request(
                        method="POST",
                        url=request.full_url,
                        headers=request.params,
                        content=request.payload,
                    ),
                ),
                body=result.new_body,
            )
        return ObservedArgs(args=args, kwargs=kwargs)
