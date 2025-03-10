#  Copyright 2023-2024 AllTrue.ai Inc
#  All Rights Reserved.
#
#  NOTICE: All information contained herein is, and remains
#  the property of AllTrue.ai Incorporated. The intellectual and technical
#  concepts contained herein are proprietary to AllTrue.ai Incorporated
#  and may be covered by U.S. and Foreign Patents,
#  patents in process, and are protected by trade secret or copyright law.
#  Dissemination of this information or reproduction of this material
#  is strictly forbidden unless prior written permission is obtained
#  from AllTrue.ai Incorporated.
import glob
import os
import pathlib
import tomllib

_CORE_HOME = os.path.join("core", "src")


def pdm_build_update_files(context, files):
    context.config.metadata.pop("optional-dependencies")
    with open(
        os.path.join(_CORE_HOME, "..", "pyproject.toml"), "rb"
    ) as core_project_file:
        core_project = tomllib.load(core_project_file)
        context.config.metadata["dependencies"].extend(
            core_project["project"]["dependencies"]
        )
    for src in glob.glob(os.path.join(_CORE_HOME, "**", "*.py"), recursive=True):
        files[src.removeprefix(_CORE_HOME + os.path.sep)] = pathlib.Path(
            os.path.abspath(src)
        )
