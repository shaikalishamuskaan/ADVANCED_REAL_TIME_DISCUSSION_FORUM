import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.clients.author_cache import get_author_profile


@pytest.mark.asyncio
async def test_author_profile_cache_hit():
    user_id = uuid4()

    profile = {
        "id": str(user_id),
        "username": "ali",
        "display_name": "Ali",
        "avatar_url": None,
    }

    redis = AsyncMock()
    redis.get.return_value = json.dumps(profile)

    result = await get_author_profile(
        redis=redis,
        user_id=user_id,
        fallback_username="ali",
    )

    assert result == profile
    redis.set.assert_not_called()


@pytest.mark.asyncio
async def test_author_profile_fallback_when_identity_unavailable(monkeypatch):
    user_id = uuid4()

    async def fake_fetch_user_profiles(user_ids):
        raise RuntimeError("Identity unavailable.")

    monkeypatch.setattr(
        "app.clients.author_cache.fetch_user_profiles",
        fake_fetch_user_profiles,
    )

    redis = AsyncMock()
    redis.get.return_value = None

    result = await get_author_profile(
        redis=redis,
        user_id=user_id,
        fallback_username="ali",
    )

    assert result == {
        "id": str(user_id),
        "username": "ali",
        "display_name": "ali",
        "avatar_url": None,
    }