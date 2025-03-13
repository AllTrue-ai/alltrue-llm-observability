#  Copyright 2025 AllTrue.ai
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

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class HttpStatus(IntEnum):
    OK = 200
    MOVED_PERMANENTLY = 301
    TEMPORARY_REDIRECT = 307
    PERMANENT_REDIRECT = 308
    UNAUTHORIZED = 401
    FORBIDDEN = 403
