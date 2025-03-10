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
import os

TEST_PROMPT_CANARY = "35494653-15b8-4a3f-99e1-04832cb98d9f"
TEST_PROMPT_SUBSTITUTION = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(TESTS_DIR, "..")
APP_DIR = os.path.join(PROJECT_DIR, "src")
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
ENV_FILE_PATH = os.path.join(PROJECT_DIR, ".env")


def init_servers(**kwargs):
    return (1, 2)
