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

import os
import shutil
from pathlib import Path
from subprocess import Popen

TEST_PROMPT_CANARY = "35494653-15b8-4a3f-99e1-04832cb98d9f"
TEST_PROMPT_SUBSTITUTION = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(TESTS_DIR, "..")
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
ENV_FILE_PATH = os.path.join(PROJECT_DIR, ".env")


def random_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("", 0))
    return sock.getsockname()[1]


def init_servers(
    target_url: str | None = None,
    proxy_args: list[str] = [],
) -> tuple[Popen, int, Popen, int]:
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    for p in Path(LOG_DIR).glob(f"test_*.txt"):
        p.unlink()
    for p in Path(TESTS_DIR).glob(os.path.join("_mitmproxy", "*")):
        shutil.rmtree(str(p))

    control_port = random_port()

    control_stdout_file = open(
        os.path.join(LOG_DIR, f"test_control_{control_port}_stdout.txt"), "wb"
    )
    control_stderr_file = open(
        os.path.join(LOG_DIR, f"test_control_{control_port}_stderr.txt"), "wb"
    )

    my_env = os.environ.copy()
    my_env["PYTHONPATH"] = f"{TESTS_DIR}"
    control_process = Popen(
        [
            "uvicorn",
            f"tests.mocks.control:app",
            "--port",
            f"{control_port}",
        ],
        stdout=control_stdout_file,
        stderr=control_stderr_file,
        env=my_env,
        cwd=PROJECT_DIR,
    )
    code = control_process.poll()
    assert code is None, f"Mock Control-Plane failed with code {code}"
    print(
        f"mock control-plane {'started' if code is None else 'existed:' + str(code)} as {control_process.pid}"
    )

    llm_port = random_port()
    llm_stdout_file = open(
        os.path.join(LOG_DIR, f"test_llm_{llm_port}_stdout.txt"), "wb"
    )
    llm_stderr_file = open(
        os.path.join(LOG_DIR, f"test_llm_{llm_port}_stderr.txt"), "wb"
    )

    llm_process = Popen(
        [
            os.path.join(PROJECT_DIR, "venv", "bin", "python"),
            os.path.join(PROJECT_DIR, "venv", "bin", "mitmdump"),
            "-s",
            os.path.join(TESTS_DIR, "mocks", "openai.py"),
            "--set",
            f"confdir={os.path.join(TESTS_DIR, '_mitmproxy', str(llm_port))}",
            "--set",
            "connection_strategy=lazy",
            *proxy_args,
            "--mode=regular" if target_url is None else f"--mode=reverse:{target_url}",
            "-p",
            str(llm_port),
        ],
        stdout=llm_stdout_file,
        stderr=llm_stderr_file,
        env=my_env,
        cwd=PROJECT_DIR,
    )
    code = llm_process.poll()
    assert code is None, f"Mock Proxy failed with code {code}"
    print(
        f"mitmproxy {'started' if code is None else 'existed:' + str(code)} as {llm_process.pid}"
    )

    return control_process, control_port, llm_process, llm_port
