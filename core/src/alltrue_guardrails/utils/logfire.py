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
import importlib.util
from contextlib import contextmanager
from typing import Any


class LogfireMock:
    """Mock version of logfire that preserves function behavior when used as a decorator (logfire.instrument),
    context manager (logfire.span) or methods (logfire.info)"""

    @staticmethod
    def instrument(*args, **kwargs):
        def decorator(func):
            return func  # Return the function unmodified

        return decorator

    # context manager "span"
    @contextmanager
    def span(self, *args, **kwargs):
        yield None

    def __getattr__(self, name):
        """Return a no-op function for any other logfire methods."""
        return lambda *args, **kwargs: None


INITIALIZED_LOGFIRE = None


def configure_logfire() -> Any:
    """
    Configure logfire for logging.
    Logfire is an optional dependency which may not be installed, in which case we mock it to prevent errors.
    """
    global INITIALIZED_LOGFIRE
    if INITIALIZED_LOGFIRE is not None:
        return INITIALIZED_LOGFIRE

    if importlib.util.find_spec("logfire") is not None:
        import logfire

        logfire.configure(
            send_to_logfire="if-token-present", scrubbing=False, metrics=False
        )
        logfire.instrument_httpx()
        import logging

        logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()])
        INITIALIZED_LOGFIRE = logfire
    else:
        logfire = LogfireMock()
        INITIALIZED_LOGFIRE = logfire

    return INITIALIZED_LOGFIRE
