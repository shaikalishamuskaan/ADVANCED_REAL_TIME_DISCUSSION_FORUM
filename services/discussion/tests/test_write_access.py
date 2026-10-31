from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.dependencies.write_access import write_access
from app.core.security import AuthenticatedUser


class FakeRedis:
    def __init__(self):
        self.count = 0

    async def eval(self, script, number_of_keys, key, window):
        self.count += 1
        return [self.count, window]

    async def get(self, key):
        return None

    async def set(self, key, value, ex):
        pass


@pytest.mark.asyncio
async def test_write_pipeline_checks_rate_limit_and_status(
    monkeypatch,
):
    user_id = uuid4()

    current_user = AuthenticatedUser(
        user_id=user_id,
        username="test_user",
        role="member",
    )

    redis = FakeRedis()

    calls = []

    async def fake_rate_limit(**kwargs):
        calls.append("rate_limit")

    async def fake_active_user(current_user, redis):
        calls.append("user_status")

        return AuthenticatedUser(
            user_id=user_id,
            username="current_username",
            role="member",
        )

    monkeypatch.setattr(
        "app.api.dependencies.write_access.enforce_rate_limit",
        fake_rate_limit,
    )

    monkeypatch.setattr(
        "app.api.dependencies.write_access.get_active_user",
        fake_active_user,
    )

    dependency = write_access(
        scope="comment_create",
        limit=30,
    )

    result = await dependency(
        current_user=current_user,
        redis=redis,
    )

    assert calls == ["rate_limit", "user_status"]
    assert result.username == "current_username"


@pytest.mark.asyncio
async def test_write_pipeline_stops_if_rate_limit_fails(
    monkeypatch,
):
    current_user = AuthenticatedUser(
        user_id=uuid4(),
        username="test_user",
        role="member",
    )

    redis = FakeRedis()

    async def fake_rate_limit(**kwargs):
        raise HTTPException(status_code=429)

    async def fake_active_user(current_user, redis):
        raise AssertionError(
            "Status check must not run after rate-limit failure."
        )

    monkeypatch.setattr(
        "app.api.dependencies.write_access.enforce_rate_limit",
        fake_rate_limit,
    )

    monkeypatch.setattr(
        "app.api.dependencies.write_access.get_active_user",
        fake_active_user,
    )

    dependency = write_access(
        scope="comment_create",
        limit=30,
    )

    with pytest.raises(HTTPException) as error:
        await dependency(
            current_user=current_user,
            redis=redis,
        )

    assert error.value.status_code == 429