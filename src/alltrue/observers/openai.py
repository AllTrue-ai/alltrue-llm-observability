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

import json
from typing import Any, cast

import httpx
from alltrue.control.chat import ProcessResult
from alltrue.http import HttpStatus
from openai import PermissionDeniedError
from openai.types.chat import ChatCompletion
from typing_extensions import override

from alltrue.observers import (
    BaseObserver,
    EndpointRequest,
    Observable,
    ObservedArgs,
    ObservedInstance,
)


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
        if (
            HttpStatus.is_success(response.status_code)
            and len(response.new_body or "") > 0
        ):
            return ChatCompletion.model_validate(json.loads(response.new_body))
        elif HttpStatus.is_unauthorized(response.status_code):
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
        if HttpStatus.is_success(result.status_code) and len(result.new_body or "") > 0:
            payload = json.loads(result.new_body)
            kwargs["model"] = payload.get("model", kwargs.get("model", None))
            kwargs["messages"] = payload.get("messages", kwargs.get("messages", []))
        elif HttpStatus.is_unauthorized(result.status_code):
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
