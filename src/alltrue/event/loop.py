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

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Coroutine


class ThreadExecutor:
    """
    Using threading to trigger event loop to ensure tasks to be run in the background
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop = asyncio.new_event_loop(),
        log_on_execution: bool = True,
        execution_interval: float = 1.0,
    ):
        """
        :param loop: the event loop this class to handle with
        :param log_on_execution: whether to log on task executions
        :param execution_interval: the interval the thread should invoke task execution
        """
        self._loop = loop
        self._tasks: set[asyncio.Task] = set()
        self._logger = logging.getLogger(__name__) if log_on_execution else None
        self._lock = threading.Lock()
        threading.Thread(
            target=self._start, args=(execution_interval,), daemon=True
        ).start()

    def _start(self, interval: float):
        while True:
            if len(self._tasks) == 0:
                time.sleep(interval)
            else:
                try:
                    self._loop.run_until_complete(asyncio.gather(*self._tasks))
                except Exception as e:
                    self._log(logging.INFO, f"[LOOP] {e}", exc_info=True)

    def _log(self, *args, **kwargs):
        if self._logger:
            self._logger.log(*args, **kwargs)

    def _task_done(self, task: asyncio.Task):
        self._log(
            logging.INFO,
            f"[LOOP] {'Cancelled' if task.cancelled() else 'Completed'} the execution of {task.get_name()}",
        )
        exc_info = task.exception()
        if exc_info:
            self._log(
                logging.INFO,
                f"[LOOP] Exception observed on {task.get_name()}",
                exc_info=exc_info,
            )
        with self._lock:
            self._tasks.discard(task)

    def ensure_future(
        self, coroutine: Coroutine[Any, Any, Any], call_back: Callable | None = None
    ) -> None:
        """
        Similar to `asyncio.ensure_future` to run the given coroutine in the background whenever the lopp is available.
        """
        task = self._loop.create_task(coroutine)
        if call_back:
            task.add_done_callback(call_back)
        task.add_done_callback(self._task_done)
        with self._lock:
            self._tasks.add(task)

    def stop(self):
        if self.is_running:
            self._loop.stop()

    def close(self):
        if not (self.is_closed or self.is_running):
            self._loop.close()
        else:
            self._log(
                logging.WARNING,
                "[LOOP] Cannot closed while already closed or still running.",
            )

    @property
    def all_tasks(self) -> set[asyncio.Task]:
        return self._tasks.copy()

    @property
    def is_running(self) -> bool:
        return self._loop.is_running()

    @property
    def is_closed(self) -> bool:
        return self._loop.is_closed()
