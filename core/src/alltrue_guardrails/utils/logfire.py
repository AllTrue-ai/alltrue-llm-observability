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
import logging
import time
from contextlib import contextmanager
from typing import Any


class LogfireMock:
    """Mock version of logfire that preserves function behavior when used as a decorator (logfire.instrument),
    context manager (logfire.span) or methods (logfire.info)"""

    def __init__(self):
        self.log = logging.getLogger("logfire")
        if not getattr(self.log, "_patched", False):
            import re

            _p = r"(\s+\([\w\{\}\s\=\(\),\"\:\[\]\'\-\#\.\/\<\>\\\?\*\%]+\s+)(\d+\.\d+s)?\s+\|"
            _r = r" | \2"
            _log = self.log.log
            self.log.log = lambda l, m, *args, **kwargs: _log(
                l,
                f"{re.sub(_p, _r, m)}".replace("<>|", "<> | "),
                *args,
                **kwargs,
            )
            setattr(self.log, "_patched", True)

    def instrument(self, *args0, **kwargs0):
        from logfunc import logf

        return logf(
            level=logging.DEBUG,
            single_msg=True,
            identifier=True,
            log_exec_time=True,
            log_args=False,
            log_return=False,
            use_logger=self.log,
        )

    # context manager "span"
    @contextmanager
    def span(self, *args, **kwargs):
        ts = time.process_time()
        yield None
        elapsed = time.process_time() - ts
        self.log.info(f"<> | {args[0] if len(args) > 0 else ''} | {elapsed:.4f}s |")

    def __getattr__(self, name):
        """Return a no-op function for any other logfire methods."""
        if hasattr(self.log, name):
            return getattr(self.log, name)
        return lambda *args, **kwargs: None


_LOGFIRE = None


def configure_logfire(force: bool = False, **kwargs) -> Any:
    """
    Configure logfire for logging.
    Logfire is an optional dependency which may not be installed, in which case we mock it to prevent errors.

    :param force: by default, configurations only set at the first time, giving this parameter as True to force setting logfire configurations.
    """
    global _LOGFIRE
    if _LOGFIRE is not None:
        if force:
            _configure(**kwargs)
        return _LOGFIRE

    if importlib.util.find_spec("logfire") is not None:
        import logfire

        _configure(**kwargs)

        logfire.instrument_httpx()
        logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()])

        _LOGFIRE = logfire

        logging.getLogger("logfire").info("Logfire enabled")
    else:
        _LOGFIRE = LogfireMock()

        logging.getLogger("logfire").info("Logfire disabled")

    return _LOGFIRE


def _configure(**kwargs):
    if importlib.util.find_spec("logfire") is not None:
        import logfire

        logfire.configure(
            send_to_logfire="if-token-present",
            scrubbing=False,
            metrics=False,
            **kwargs,
        )
