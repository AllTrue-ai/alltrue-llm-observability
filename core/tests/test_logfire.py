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
from alltrue_guardrails.utils.logfire import LogfireMock, configure_logfire


@pytest.mark.parametrize(
    "logfire",
    [
        configure_logfire(),
        LogfireMock(),
    ],
)
def test_logfire(logfire):
    @logfire.instrument("abc")
    def simple_func():
        return 1

    assert simple_func() == 1

    with logfire.span("def"):
        assert True
