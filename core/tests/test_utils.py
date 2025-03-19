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

import pytest
from alltrue_guardrails.utils.path import EndpointInfo


@pytest.mark.parametrize(
    "path, expected",
    [
        # if no endpoint identifier is found, the function should return None
        (
            "/v1",
            EndpointInfo(
                path="/v1",
                endpoint_identifier=None,
                base_url=None,
            ),
        ),
        # if have extra info but not marked with /endpoint/, should return None
        (
            "/v1/foobar/bar/baz",
            EndpointInfo(
                path="/v1/foobar/bar/baz",
                endpoint_identifier=None,
                base_url=None,
            ),
        ),
        # if have extra info and marked with /endpoint/, should return the endpoint info and the other parts are kept as is
        (
            "/v1/endpoint/foobar/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url=None,
            ),
        ),
        # same as above with /endpoint-identifier/ as the keyword
        (
            "/v1/endpoint-identifier/foobar/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url=None,
            ),
        ),
        # same as above with special identifier
        (
            "/v1/endpoint-identifier/endpoint/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="endpoint",
                base_url=None,
            ),
        ),
        # should be able to specify base url
        (
            "/v1/base-url/http://example.com/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier=None,
                base_url="http://example.com",
            ),
        ),
        # if identifier is before url, should be able to extract both
        (
            "/v1/base-url/http://example.com/endpoint/foobar/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url="http://example.com",
            ),
        ),
        # if identifier is after url, should be able to extract both
        (
            "/v1/endpoint/foobar/base-url/http://example.com/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url="http://example.com",
            ),
        ),
        # should be able to extract a proxy type from the front
        (
            "/v1/proxy-type/azure-openai/base-url/http://example.com/endpoint/foobar/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url="http://example.com",
                proxy_type="azure-openai",
            ),
        ),
        # proxy type can be in the middle between base-url and endpoint
        (
            "/v1/base-url/http://example.com/proxy-type/azure-openai/endpoint/foobar/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url="http://example.com",
                proxy_type="azure-openai",
            ),
        ),
        # proxy type can also be at the end after the endpoint
        (
            "/v1/base-url/http://example.com/endpoint/foobar/proxy-type/azure-openai/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url="http://example.com",
                proxy_type="azure-openai",
            ),
        ),
        # path parameter endpoint-identifier as well works
        (
            "/v1/base-url/http://example.com/endpoint-identifier/foobar/proxy-type/azure-openai/bar/baz",
            EndpointInfo(
                path="/v1/bar/baz",
                endpoint_identifier="foobar",
                base_url="http://example.com",
                proxy_type="azure-openai",
            ),
        ),
        (
            "/openai/base-url/https:/test-customer.openai.azure.com/proxy-type/azure-openai/deployments/test/chat/completions?api-version=2024-06-01",
            EndpointInfo(
                path="/openai/deployments/test/chat/completions?api-version=2024-06-01",
                base_url="https://test-customer.openai.azure.com",
                proxy_type="azure-openai",
                endpoint_identifier=None,
            ),
        ),
        (
            "/base-url/https:/test-customer.openai.azure.com/openai/deployments/test/chat/completions/proxy-type/azure-openai?api-version=2024-06-01",
            EndpointInfo(
                path="/openai/deployments/test/chat/completions?api-version=2024-06-01",
                base_url="https://test-customer.openai.azure.com",
                proxy_type="azure-openai",
                endpoint_identifier=None,
            ),
        ),
    ],
)
def test_extract_endpoint_info(path, expected):
    endpoint_info = EndpointInfo.parse_from_path(path)
    assert endpoint_info == expected


def test_parse_and_compose():
    path = "/v1/something/endpoint/random/base-url/https://test-customer.openai.azure.com/proxy-type/azure-openai"

    parsed = EndpointInfo.parse_from_path(path)
    assert parsed.path == "/v1/something"
    assert parsed.base_url == "https://test-customer.openai.azure.com"
    assert parsed.proxy_type == "azure-openai"
    assert parsed.endpoint_identifier == "random"

    assert parsed.compose_path() == path
