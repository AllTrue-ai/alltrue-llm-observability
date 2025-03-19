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

import logging
import re
from typing import Any, MutableMapping, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from typing_extensions import deprecated

from .config import get_or_default

HEADERS = TypeVar("HEADERS", bound=MutableMapping)


def _get_header_key(attr: str) -> str:
    return attr.lower().replace("_", "-")


def _get_header(headers: HEADERS, attr: str) -> Any | None:
    key = _get_header_key(attr)
    return headers.get(f"x-alltrue-llm-{key}", None) or headers.get(key, None)


class EndpointInfo(BaseModel):
    path: str
    endpoint_identifier: str | None = None
    base_url: str | None = None
    proxy_type: str | None = Field(
        None, description="Custom proxy type specified by the caller in base URL."
    )

    def compose_path(self) -> str:
        _url = "" if self.path.strip() == "/" else self.path.strip().removesuffix("/")
        if self.endpoint_identifier:
            _url += f"/endpoint/{self.endpoint_identifier}"
        if self.base_url:
            _url += f"/base-url/{self.base_url}"
        if self.proxy_type:
            _url += f"/proxy-type/{self.proxy_type}"
        return _url

    def compose_headers(self, headers: HEADERS) -> HEADERS:
        if self.endpoint_identifier:
            headers[f"{_get_header_key('endpoint_identifier')}"] = str(
                self.endpoint_identifier
            )
        if self.base_url:
            headers[f"{_get_header_key('base_url')}"] = str(self.base_url)
        if self.proxy_type:
            headers[f"{_get_header_key('proxy_type')}"] = str(self.proxy_type)
        return headers

    def merge(self, other: "EndpointInfo") -> "EndpointInfo":
        """
        Merge another PathElements into this one to update any of the existing attribute with None value.
        """
        self.base_url = other.base_url or self.base_url
        self.endpoint_identifier = other.endpoint_identifier or self.endpoint_identifier
        self.proxy_type = other.proxy_type or self.proxy_type
        self.path = other.path or self.path
        return self

    @classmethod
    def parse_from_path(cls, path: str) -> "EndpointInfo":
        """
        Finds the endpoint name and base URL in the given path. Returns an EndpointInfo
        object containing the endpoint name, remaining path, endpoint identifier,
        and base URL if present.

        Args:
            path (str): The input URL path.

        Returns:
            EndpointInfo: A Pydantic model containing the extracted data.
        """
        endpoint_markers = ["/endpoint-identifier/", "/endpoint/"]
        base_url_marker = "/base-url/"
        proxy_type_marker = "/proxy-type/"

        endpoint_identifier = None
        base_url = None
        proxy_type = None
        remaining_path = path

        # Check if the path contains "/endpoint/"
        for endpoint_marker in endpoint_markers:
            if endpoint_marker in path:
                prefix, suffix = path.split(endpoint_marker, 1)
                endpoint_parts = suffix.split("/", 1)
                endpoint_identifier = endpoint_parts[0]
                if len(endpoint_parts) > 1:
                    remaining_path = f"{prefix}/{endpoint_parts[1]}"
                else:
                    remaining_path = prefix
                break

        # Check if the path contains "/base-url/"
        if base_url_marker in remaining_path:
            # Capture everything after "/base-url/" as the base URL
            prefix, base_url_override = remaining_path.split(base_url_marker, 1)
            # extract the scheme from the base URL
            if ":/" in base_url_override:
                (
                    base_url_override_scheme,
                    base_url_override_url,
                ) = base_url_override.split(":/", 1)
                (
                    base_url_override_root,
                    base_url_override_path,
                ) = base_url_override_url.removeprefix("/").split("/", 1)
                base_url = f"{base_url_override_scheme}://{base_url_override_root}"
                remaining_path = f"{prefix}/{base_url_override_path}"
            else:
                # Split the remaining path after the base URL if present
                if base_url and "/" in base_url:
                    base_url, remaining_path = base_url.split("/", 1)
                    remaining_path = f"{prefix}/{remaining_path}"
                else:
                    remaining_path = prefix

        # Check if the path contains "/proxy-type/"
        if proxy_type_marker in remaining_path:
            prefix, suffix = remaining_path.split(proxy_type_marker, 1)
            proxy_type_parts = suffix.split("/", 1)
            proxy_type = proxy_type_parts[0]
            if len(proxy_type_parts) > 1:
                remaining_path = f"{prefix}/{proxy_type_parts[1]}"
            else:
                remaining_path = prefix

            if "?" in proxy_type:
                prefix, suffix = proxy_type.split("?", 1)
                proxy_type = prefix
                remaining_path = f"{remaining_path}?{suffix}"

        # remove /custom from host and remaining path
        if base_url and base_url.endswith("/custom"):
            base_url = base_url.removesuffix("/custom")

        if remaining_path and remaining_path.startswith("/custom"):
            remaining_path = remaining_path.removeprefix("/custom")

        return EndpointInfo(
            path=remaining_path,
            endpoint_identifier=endpoint_identifier,
            base_url=base_url,
            proxy_type=proxy_type,
        )

    @classmethod
    def parse_from_headers(cls, headers: HEADERS) -> "EndpointInfo":
        return EndpointInfo(
            path="",
            endpoint_identifier=_get_header(headers, "endpoint_identifier"),
            base_url=_get_header(headers, "base_url"),
            proxy_type=_get_header(headers, "proxy_type"),
        )


@deprecated("Replaced by new mitmproxy option `domain_matchers` and `path_matchers`")
class UrlVerifier:
    def __init__(self, domain_matcher: str = "$^", path_matcher: str = "$^"):
        self._dm = re.compile(domain_matcher)
        self._pm = re.compile(path_matcher)

    def is_interested(self, url: str) -> bool:
        _u = urlparse(url)
        logging.info(f"verifying {_u.hostname} + {_u.path}")
        return (
            _u.hostname is not None
            and re.match(self._dm, _u.hostname) is not None
            and re.match(self._pm, _u.path) is not None
        )

    @classmethod
    def get_by_type(cls, proxy_type: str) -> "UrlVerifier":
        match proxy_type:
            case "openai" | "azure-openai":
                # only support v1 of openai API (both for openai client and azure openai client)
                return UrlVerifier(
                    domain_matcher=".*",
                    path_matcher="/v1/chat/completions.*",
                )
            case "anthropic":
                return UrlVerifier(
                    domain_matcher=".*",
                    path_matcher="/v1/messages.*",
                )
            case "google":
                # GenerateContent for both input/output and BatchEmbedContents for input only
                return UrlVerifier(
                    domain_matcher=".*",
                    path_matcher=".*([Gg]enerate|[Bb]atch[Ee]mbed)[Cc]ontent[s]?.*",
                )
            case "ibmwatsonx":
                return UrlVerifier(
                    domain_matcher=".*",
                    path_matcher="/ml/v1/text/chat.*",
                )
            case "custom" | "any":
                return UrlVerifier(
                    domain_matcher=get_or_default("domain_matcher", ".*"),
                    path_matcher=get_or_default("path_matcher", ".*"),
                )
            case _:
                logging.warning(f"[ERR] Unsupported proxy type: {proxy_type}")
                return UrlVerifier()
