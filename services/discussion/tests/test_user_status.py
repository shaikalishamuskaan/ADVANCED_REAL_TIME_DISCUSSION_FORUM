import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.dependencies import user_status
from app.core.security import AuthenticatedUser


class FakeRedis:
    def __init__(self, cached_data=None):
        self.cached_data = cached_data
        self.saved = {}

    async def get(self, key):
        return self.cached_data

    async def set(self, key, value, ex):
        self.saved[key] = {
            "value": value,
            "expiry": ex,
        }


class FailingRedis:
    async def get(self, key):
        from redis.exceptions import ConnectionError
        raise ConnectionError("Redis unavailable")


@pytest.fixture
def current_user():
    return AuthenticatedUser(
        user_id=uuid4(),
        username="old_username",
        role="member",
    )


@pytest.mark.asyncio
async def test_active_user_uses_cached_status(
    current_user,
    monkeypatch,
):
    cached = {
        "id": str(current_user.user_id),
        "username": "current_username",
        "role": "moderator",
        "status": "active",
    }

    redis = FakeRedis(json.dumps(cached))

    async def unexpected_identity_call(user_id):
        raise AssertionError("Identity should not be called.")

    monkeypatch.setattr(
        user_status,
        "fetch_user_status",
        unexpected_identity_call,
    )

    result = await user_status.get_active_user(
        current_user,
        redis,
    )

    assert result.username == "current_username"
    assert result.role == "moderator"


@pytest.mark.asyncio
async def test_cache_miss_fetches_identity(
    current_user,
    monkeypatch,
):
    redis = FakeRedis()

    async def fake_identity_call(user_id):
        return {
            "id": user_id,
            "username": "test_user",
            "role": "member",
            "status": "active",
        }

    class FakeSettings:
        STATUS_CACHE_TTL_SECONDS = 30

    monkeypatch.setattr(
        user_status,
        "fetch_user_status",
        fake_identity_call,
    )

    monkeypatch.setattr(
        user_status,
        "get_settings",
        lambda: FakeSettings(),
    )

    result = await user_status.get_active_user(
        current_user,
        redis,
    )

    assert result.role == "member"
    assert len(redis.saved) == 1


@pytest.mark.asyncio
async def test_disabled_user_is_rejected(
    current_user,
    monkeypatch,
):
    disabled = {
        "id": str(current_user.user_id),
        "username": "test_user",
        "role": "member",
        "status": "disabled",
    }

    redis = FakeRedis(json.dumps(disabled))

    with pytest.raises(HTTPException) as error:
        await user_status.get_active_user(
            current_user,
            redis,
        )

    assert error.value.status_code == 403
    assert (
        error.value.detail["error"]["code"]
        == "account_disabled"
    )


@pytest.mark.asyncio
async def test_redis_failure_returns_503(current_user):
    with pytest.raises(HTTPException) as error:
        await user_status.get_active_user(
            current_user,
            FailingRedis(),
        )

    assert error.value.status_code == 503