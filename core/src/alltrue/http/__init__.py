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

from enum import IntEnum
from typing import Literal

import httpx

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class HttpStatus(IntEnum):
    """
    HTTP Status Codes wrapping from httpx
    """

    OK = httpx.codes.OK
    MOVED_PERMANENTLY = httpx.codes.MOVED_PERMANENTLY.value
    TEMPORARY_REDIRECT = httpx.codes.TEMPORARY_REDIRECT.value
    PERMANENT_REDIRECT = httpx.codes.PERMANENT_REDIRECT.value
    UNAUTHORIZED = httpx.codes.UNAUTHORIZED.value
    FORBIDDEN = httpx.codes.FORBIDDEN.value

    @classmethod
    def is_success(cls, value: int) -> bool:
        return httpx.codes.is_success(value)

    @classmethod
    def is_redirect(cls, value: int) -> bool:
        return httpx.codes.is_redirect(value)

    @classmethod
    def is_error(cls, value: int) -> bool:
        return httpx.codes.is_error(value)

    @classmethod
    def is_unauthorized(cls, value: int) -> bool:
        return value in [httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN]
