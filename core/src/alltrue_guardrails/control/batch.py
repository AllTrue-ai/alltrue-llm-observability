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

import uuid

from ..utils.logfire import configure_logfire  # isort:skip

logfire = configure_logfire()  # isort:skip

import asyncio
import itertools
import json
import logging
import re
from typing import Any, Callable, Coroutine, NamedTuple

import httpx
from async_batcher.batcher import AsyncBatcher
from typing_extensions import override

from ..http import HttpMethod, HttpStatus
from .chat import RuleProcessor

_DEFAULT_BATCH_TIMEOUT = 3.0


class _Request(NamedTuple):
    endpoint: str
    method: HttpMethod
    body: dict | None


class _BatchCaller(AsyncBatcher[_Request, httpx.Response]):
    """
    Internal usage to call control batch APIs by batch
    """

    def __init__(
        self,
        *,
        func: Callable[
            [str, HttpMethod, dict | None, float | None, bool],
            Coroutine[Any, Any, httpx.Response],
        ],
        logger: logging.Logger,
        **kwargs,
    ):
        super().__init__(
            **kwargs,
        )
        self._func = func
        self._key_func = lambda r: f"[{r.method}]{r.endpoint}"
        self.log = logger

    @logfire.instrument()
    async def process_batch(self, batch: list[_Request]) -> list[httpx.Response] | None:
        _batch_id = str(uuid.uuid4())[:8]
        self.log.debug(
            f"Batch:{_batch_id} started handling {len(batch)} requests in queue..."
        )

        calls = []
        for key, requests in itertools.groupby(
            sorted(batch, key=self._key_func), key=self._key_func
        ):
            parsed_key = re.search(r"\[(.*)\](.*)", key)
            if not parsed_key:
                continue
            (method, endpoint) = parsed_key.groups()
            batch_endpoint = f"/batch/{endpoint.removeprefix('/')}"
            batch_body = [
                request.body
                for request in filter(lambda r: r.body is not None, requests)
            ]
            calls.append(
                self._func(
                    batch_endpoint,
                    method,  # type: ignore
                    {"requests": batch_body} if len(batch_body) > 0 else None,
                    _DEFAULT_BATCH_TIMEOUT,
                    False,  # no cache for batch
                )
            )
        try:
            responses = await asyncio.wait_for(
                asyncio.gather(*calls, return_exceptions=True),
                timeout=_DEFAULT_BATCH_TIMEOUT,
            )
        except Exception as e:
            responses = [e]
        for response in responses:
            match response:
                case exc if isinstance(exc, Exception):
                    self.log.warning(
                        f"Batch:{_batch_id} exception occurred", exc_info=exc
                    )
                case res if isinstance(res, httpx.Response):
                    if HttpStatus.is_error(res.status_code):
                        self.log.warning(
                            f"Batch:{_batch_id} request unsuccessful - {res.status_code}:{res.text}"
                        )
        self.log.info(f"Batch:{_batch_id} handled {len(batch)} requests in queue")
        # no need to handle other results
        return None


class BatchRuleProcessor(RuleProcessor):
    """
    Processing chat requests/responses in batch
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        customer_id: str | None = None,
        llm_api_provider: str | None = None,
        logging_level: int | str = logging.INFO,
        batch_size: int = 5,
        queue_time: float = _DEFAULT_BATCH_TIMEOUT,
        **kwargs,
    ):
        super().__init__(
            api_url=api_url,
            api_key=api_key,
            customer_id=customer_id,
            llm_api_provider=llm_api_provider,
            logging_level=logging_level,
            **kwargs,
        )

        self.log = logging.getLogger("alltrue.api.batcher")
        self._batcher = _BatchCaller(
            func=super()._chat,
            logger=self.log,
            concurrency=3,
            max_batch_size=batch_size,
            max_queue_time=queue_time,
        )

    @override
    @logfire.instrument()
    async def _chat(
        self,
        endpoint: str,
        method: HttpMethod = "POST",
        body: dict | None = None,
        timeout: float | None = None,
        cache: bool = False,
    ) -> httpx.Response:
        matched = re.search(r"/process-(input|output)/.*", endpoint)
        endpoint_type = matched.group(1) if matched else None
        if endpoint_type is not None:
            await self._batcher.process(
                _Request(endpoint=endpoint, method=method, body=body)
            )
            self.log.debug(f"Reqeust {endpoint} batched")
            payload_type = "request" if endpoint_type == "input" else "response"
            return httpx.Response(
                status_code=HttpStatus.OK,
                content=json.dumps(
                    {
                        "status_code": HttpStatus.OK,
                        f"processed_{endpoint_type}": json.loads(
                            body.get(f"original_{payload_type}_body", "{}")
                            if body
                            else "{}"
                        ),
                        "message": f"Reqeust batched",
                    }
                ),
            )
        else:
            return await super()._chat(
                endpoint=endpoint,
                method=method,
                body=body,
                timeout=timeout,
                cache=cache,
            )

    @property
    @override
    async def is_running(self) -> bool:
        return all(await asyncio.gather(super().is_running, self._batcher.is_running()))

    @override
    async def close(self, timeout: float | None = None) -> None:
        self.log.info("Closing batcher...")
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    super().close(),
                    self._batcher.stop(),
                ),
                timeout=timeout,
            )
            self.log.info("Batcher closed!")
        except TimeoutError:
            self.log.warning("Batcher closure timed out, some batches might be lost!")

    @classmethod
    def clone(
        cls,
        original: RuleProcessor,
        batch_size: int = 5,
        queue_time: float = _DEFAULT_BATCH_TIMEOUT,
    ) -> "BatchRuleProcessor":
        """
        Copy constructor
        """
        if isinstance(original, cls):
            return cls(
                _config=original.config,
                _client=original._client,
                batch_size=original._batcher.max_batch_size,
                queue_time=original._batcher.max_queue_time,
            )
        else:
            return cls(
                _config=original.config,
                _client=original._client,
                batch_size=batch_size,
                queue_time=queue_time,
            )
