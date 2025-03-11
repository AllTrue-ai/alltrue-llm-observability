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
from hashlib import blake2b
from typing import Callable, NamedTuple

import hishel
import httpx
from alltrue.http import HttpMethod
from alltrue.utils.config import get_or_default
from httpcore import Request, Response
from typing_extensions import override


def _get_http_timeout_config() -> httpx.Timeout:
    timeout_value = get_or_default(
        "HTTP_TIMEOUT", prefix="CONFIG", default="default"
    ).lower()

    # Convert the timeout value to the appropriate format
    if timeout_value == "none":
        timeout = httpx.Timeout(None)  # No timeout
    elif timeout_value == "default":
        timeout = None  # Use httpx default timeout
    else:
        timeout = httpx.Timeout(float(timeout_value))  # Custom timeout in seconds
    return timeout


def _get_http_transport_config(
    verify: bool = True,
    keep_alive: str | None = None,
) -> httpx.AsyncHTTPTransport | None:
    keepalive_value = (
        keep_alive
        or get_or_default(
            name="HTTP_KEEPALIVE", prefix="CONFIG", default="default"
        ).lower()
    )
    if keepalive_value in ["none", "no", "disabled", "0"]:
        # do not keep alive and reopen connection on every request to prevent event loop closed error
        # which is very likely to happen on pytesting async code
        # see https://github.com/encode/httpx/discussions/2959#discussioncomment-7665278
        return httpx.AsyncHTTPTransport(
            verify=verify,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=0),
        )
    else:
        # use default keep alive settings
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

    def register_cachable(self, cachable: CachableEndpoint):
        self._registries.append(cachable)


class CachableHttpClient(httpx.AsyncClient):
    def __init__(
        self,
        base_url: str,
        verify: bool = True,
        cache_ttl: int = 600,
        cache_capacity: int = 32,
        _keep_alive: str | None = None,
    ):
        self._controller = PathBasedCacheController()
        super().__init__(
            base_url=base_url,
            timeout=_get_http_timeout_config(),
            transport=hishel.AsyncCacheTransport(
                transport=_get_http_transport_config(
                    verify=verify, keep_alive=_keep_alive
                )
                or httpx.AsyncHTTPTransport(verify=verify),
                storage=hishel.AsyncInMemoryStorage(
                    ttl=cache_ttl,
                    capacity=cache_capacity,
                ),
                controller=self._controller,
            ),
        )

    def register_cachable(self, cachable: CachableEndpoint):
        self._controller.register_cachable(cachable)
