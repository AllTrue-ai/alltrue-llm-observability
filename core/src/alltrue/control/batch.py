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
import itertools
import json
import logging
import re
from typing import Any, Callable, Coroutine, NamedTuple

import httpx
from alltrue.control.chat import RuleProcessor
from alltrue.http import HttpStatus
from async_batcher.batcher import AsyncBatcher
from typing_extensions import override

logger = logging.getLogger(__name__)


class _Request(NamedTuple):
    endpoint: str
    body: dict


class _BatchCaller(AsyncBatcher[_Request, httpx.Response]):
    """
    Internal usage to call control batch APIs by batch
    """

    def __init__(
        self,
        *,
        func: Callable[[str, dict, bool], Coroutine[Any, Any, httpx.Response]],
        **kwargs,
    ):
        super().__init__(
            **kwargs,
        )
        self._func = func
        self._key_func = lambda r: r.endpoint

    async def process_batch(self, batch: list[_Request]) -> list[httpx.Response] | None:
        logger.info(f"[BAT] Handling {len(batch)} requests in queue...")
        calls = []
        for endpoint, requests in itertools.groupby(
            sorted(batch, key=self._key_func), key=self._key_func
        ):
            batch_endpoint = f"/batch/{endpoint.removeprefix('/')}"
            batch_body = [request.body for request in requests]
            logger.info(
                f"[BAT] Calling {batch_endpoint} with {len(batch_body)}/{len(batch)} of overall requests"
            )
            calls.append(self._func(batch_endpoint, {"requests": batch_body}, False))
        responses = await asyncio.gather(*calls, return_exceptions=True)
        for response in responses:
            match response:
                case exc if isinstance(exc, Exception):
                    logger.warning("[BAT] Exception occurred", exc_info=exc)
                case res if isinstance(res, httpx.Response):
                    if HttpStatus.is_error(res.status_code):
                        logger.warning(
                            f"[BAT] Request batch API unsuccessful: {res.status_code}:{res.text}"
                        )
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
        _connection_keep_alive: str | None = None,
        batch_size: int = 10,
        queue_time: float = 5.0,
        **kwargs,
    ):
        super().__init__(
            api_url,
            api_key,
            customer_id,
            llm_api_provider,
            _connection_keep_alive,
            **kwargs,
        )
        self._batcher = _BatchCaller(
            func=super()._call_control,
            max_batch_size=batch_size,
            max_queue_time=queue_time,
        )

    @override
    async def _call_control(
        self, endpoint: str, body: dict, cache: bool = False
    ) -> httpx.Response:
        matched = re.search(r"/process-(input|output)/.*", endpoint)
        endpoint_type = matched.group(1) if matched else None
        if endpoint_type is not None:
            logger.info(f"[BAT] Batching {endpoint} request...")
            t = asyncio.ensure_future(
                self._batcher.process(_Request(endpoint=endpoint, body=body))
            )
            payload_type = "request" if endpoint_type == "input" else "response"
            return httpx.Response(
                status_code=HttpStatus.OK,
                content=json.dumps(
                    {
                        "status_code": HttpStatus.OK,
                        f"processed_{endpoint_type}": json.loads(
                            body.get(f"original_{payload_type}_body", "{}")
                        ),
                        "message": f"Batched as {t}",
                    }
                ),
            )
        else:
            return await super()._call_control(endpoint, body, cache)

    @property
    @override
    async def is_running(self) -> bool:
        return all(await asyncio.gather(super().is_running, self._batcher.is_running()))

    @override
    async def close(self, timeout: float | None = None) -> None:
        logger.info(f"[BAT] Closing...")
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    super().close(),
                    self._batcher.stop(),
                ),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning("[BAT] Batch closing timed out, some events might be lost")

    @classmethod
    def clone(
        cls,
        original: RuleProcessor,
        batch_size: int = 10,
        queue_time: float = 10.00,
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
