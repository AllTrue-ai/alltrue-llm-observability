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

import glob
import os
import pathlib
import tomllib

_CORE_HOME = os.path.join("core", "src")


def pdm_build_update_files(context, files):
    # to build wheel bundles core lib
    optionals = context.config.metadata.pop("optional-dependencies", dict())
    context.config.metadata["optional-dependencies"] = dict(
        filter(lambda dep: "observers" in dep[0], optionals.items())
    )

    core_project = os.path.join(_CORE_HOME, "..", "pyproject.toml")
    if os.path.exists(core_project):
        with open(core_project, "rb") as core_project_file:
            core_project_config = tomllib.load(core_project_file)
            if not "dependencies" in context.config.metadata:
                context.config.metadata["dependencies"] = []
            context.config.metadata["dependencies"] = list(
                filter(
                    lambda dep: "alltrue-llm-observability-core" not in dep,
                    context.config.metadata.pop("dependencies", []),
                )
            )
            context.config.metadata["dependencies"].extend(
                core_project_config["project"]["dependencies"]
            )
        src_prefix = (
            (_CORE_HOME + os.path.sep)
            if context.target == "wheel"
            else ("core" + os.path.sep)
        )
        for src in glob.glob(os.path.join(_CORE_HOME, "**", "*.py"), recursive=True):
            files[src.removeprefix(src_prefix)] = pathlib.Path(os.path.abspath(src))
