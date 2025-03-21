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

from ..utils.logfire import configure_logfire  # isort:skip

logfire = configure_logfire()  # isort:skip


import logging
from hashlib import blake2b
from typing import Callable, NamedTuple

import hishel
import httpx
from httpcore import Request, Response
from typing_extensions import override

from ..utils.config import get_or_default
from . import HttpMethod


def _get_http_timeout_config(
    logger: logging.Logger,
    timeout: float | None = None,
) -> httpx.Timeout:
    if timeout is None:
        timeout_value = get_or_default(
            "HTTP_TIMEOUT", prefix="CONFIG", default="default"
        ).lower()
        if timeout_value == "none":
            timeout = -1
        elif timeout_value == "default":
            logging.debug("HTTP_TIMEOUT is set to default, using default timeout")
        else:
            timeout = float(timeout_value)

    # Convert the timeout value to the appropriate format
    if timeout is None:
        logger.debug("Using default timeout")
        httpx_timeout = None  # Use httpx default timeout
    elif timeout < 0:
        logger.info("HTTP timeout disabled")
        httpx_timeout = httpx.Timeout(None)  # No timeout
    else:
        logger.info(f"HTTP Timeout set to {timeout}s")
        httpx_timeout = httpx.Timeout(timeout)  # Custom timeout in seconds
    return httpx_timeout


def _get_http_transport_config(
    logger: logging.Logger,
    verify: bool = True,
    keep_alive: bool | None = None,
    retries: int = 0,
) -> httpx.AsyncHTTPTransport | None:
    if keep_alive is None:
        keepalive_value = (
            keep_alive
            or get_or_default(
                name="HTTP_KEEPALIVE", prefix="CONFIG", default="default"
            ).lower()
        )
    else:
        keepalive_value = str(keep_alive).lower()

    if keepalive_value in ["none", "no", "disabled", "0", "false"]:
        # do not keep alive and reopen connection on every request to prevent event loop closed error
        # which is very likely to happen on pytesting async code
        # see https://github.com/encode/httpx/discussions/2959#discussioncomment-7665278
        logger.info("HTTP keep-alive disabled")
        return httpx.AsyncHTTPTransport(
            verify=verify,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=0,
            ),
            retries=retries,
        )
    else:
        # use default keep alive settings
        logger.debug("HTTP keep-alive is set to default")
        return None


class CachableEndpoint(NamedTuple):
    path: str
    methods: list[HttpMethod]
    key_generator: Callable[[Request, bytes], bytes] = lambda r, b: b


class PathBasedCacheController(hishel.Controller):
    def __init__(
        self,
        *args,
        registries: list[CachableEndpoint] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._registries = registries or []
        self._default_key_generator = self._key_generator  # type: ignore
        self._key_generator = self._generate_key

    def _generate_key(self, request: Request, body: bytes = b"") -> str:
        for registry in self._registries:
            if request.url.target.startswith(registry.path.encode("utf-8")):
                key = blake2b(digest_size=16, usedforsecurity=False)
                key.update(registry.path.encode("utf-8"))
                key.update(request.method)
                key.update(registry.key_generator(request, body))
                return key.hexdigest()
        return self._default_key_generator(request, body)

    @override  # type: ignore
    def is_cachable(self, request: Request, response: Response) -> bool:
        matched = False
        if len(self._registries) > 0:
            _path = request.url.target
            _method = request.method.decode("utf-8")
            for registry in self._registries:
                if (
                    _path.startswith(registry.path.encode("utf-8"))
                    and _method in registry.methods
                ):
                    return True
        return matched or super().is_cachable(request, response)

    def is_registered(self, endpoint: str) -> bool:
        return any(
            [
                endpoint.startswith(reg.path) or reg.path.startswith(endpoint)
                for reg in self._registries
            ]
        )

    def register_cachable(
        self, cachable: CachableEndpoint, update: bool = False
    ) -> None:
        if not self.is_registered(cachable.path):
            self._registries.append(cachable)
        elif update:
            # update registered with the given one
            for registry in self._registries:
                if cachable.path.startswith(registry.path) or registry.path.startswith(
                    cachable.path
                ):
                    self._registries.remove(registry)
                    self._registries.append(
                        CachableEndpoint(
                            path=min(cachable.path, registry.path),
                            methods=list({*cachable.methods, *registry.methods}),
                            key_generator=cachable.key_generator,
                        )
                    )
                    break


class CachableHttpClient(httpx.AsyncClient):
    """
    Cache enabled HTTP client accepts path based caching rules.
    """

    def __init__(
        self,
        base_url: str,
        logger: logging.Logger = logging.getLogger("alltrue.http"),
        verify: bool = True,
        timeout: float | None = 1.0,
        retries: int | None = None,
        cache_ttl: int = 600,
        cache_capacity: int = 32,
        keep_alive: bool | None = None,
    ):
        """
        :param base_url: base url to make requests against
        :param verify: whether to verify TLS certificates
        :param timeout: HTTP request timeout; set to None to use system default, set to negative number to disable.
        :param retries: HTTP request retries; set to 0 to disable.
        :param cache_ttl: HTTP request cache TTL; set to None to disable.
        :param cache_capacity: HTTP request cache capacity; set to 0 to disable.
        """
        self._controller = PathBasedCacheController()
        super().__init__(
            base_url=base_url,
            timeout=_get_http_timeout_config(logger=logger, timeout=timeout),
            transport=hishel.AsyncCacheTransport(
                transport=_get_http_transport_config(
                    logger=logger,
                    verify=verify,
                    keep_alive=keep_alive,
                    retries=retries or 0,
                )
                or httpx.AsyncHTTPTransport(verify=verify),
                storage=hishel.AsyncInMemoryStorage(
                    ttl=cache_ttl,
                    capacity=cache_capacity,
                ),
                controller=self._controller,
            ),
        )

    @logfire.instrument()
    def register_cachable(self, cachable: CachableEndpoint):
        self._controller.register_cachable(cachable)
