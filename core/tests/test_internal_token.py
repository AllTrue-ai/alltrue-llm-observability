#
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
#
import pytest
from alltrue.control._internal.token import TokenRetriever
from alltrue.utils.config import AlltrueConfig


@pytest.mark.skip(
    reason="Test only when necessary as it will request a real Auth0 token"
)
@pytest.mark.asyncio
async def test_get_internal_access_token():
    config = AlltrueConfig(**{})
    retriever = TokenRetriever(config=config)
    token = await retriever.get_token(refresh=True)
    assert token is not None
    assert token != "__placeholder__"
    assert token == await retriever.get_token(refresh=False)
