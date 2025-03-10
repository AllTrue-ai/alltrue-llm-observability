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

from dotenv import load_dotenv
from pydantic import BaseModel, BeforeValidator
from typing_extensions import Annotated

load_dotenv()


def get_or_default(name: str, prefix: str | None = None, default: str | None = None):
    key = f"{prefix.upper()}_{name.upper()}" if prefix else name.upper()
    return os.environ.get(f"{key}", default)


def get_value(name: str, prefix: str = "ALLTRUE"):
    value = get_or_default(name=name, prefix=prefix)
    if not value:
        raise RuntimeError(
            f"Config **{prefix.upper()}_{name.upper()}** is required but not set"
        )
    return value


def _get_api_url():
    return get_value(name="api_url")


def _get_customer_id():
    return get_value(name="customer_id")


def _get_api_key():
    return get_value(name="api_key")


def _get_api_provider():
    _provider = get_or_default(name="LLM_API_PROVIDER", prefix="CONFIG", default=None)
    match _provider or get_value(name="proxy_type", prefix="CONFIG"):
        case "gemini":
            # workaround until the corresponding settings of demo env could be aligned
            return "google"
        case _ibm_proxy if _ibm_proxy.startswith("ibmwatsonx"):
            # workaround for ibmwatsonx proxies
            return "ibmwatsonx"
        case others:
            return others


class AlltrueConfig(BaseModel):
    api_url: Annotated[str | None, BeforeValidator(lambda a: a or _get_api_url())]
    api_key: Annotated[str | None, BeforeValidator(lambda a: a or _get_api_key())]
    customer_id: Annotated[
        str | None, BeforeValidator(lambda a: a or _get_customer_id())
    ]
    llm_api_provider: Annotated[
        str | None, BeforeValidator(lambda a: a or _get_api_provider())
    ]
