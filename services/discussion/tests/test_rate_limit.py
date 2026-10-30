from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from app.api.dependencies.rate_limit import enforce_rate_limit


class FakeRedis:
    def __init__(self, count, ttl=60):
        self.count = count
        self.ttl = ttl
        self.calls = []

    async def eval(self, script, number_of_keys, key, window):
        self.calls.append(
            {
                "script": script,
                "number_of_keys": number_of_keys,
                "key": key,
                "window": window,
            }
        )

        return [self.count, self.ttl]


class FailingRedis:
    async def eval(self, *args):
        raise ConnectionError("Redis is unavailable.")


@pytest.mark.asyncio
async def test_request_within_limit_is_allowed():
    redis = FakeRedis(count=1)
    user_id = uuid4()

    result = await enforce_rate_limit(
        redis=redis,
        user_id=user_id,
        scope="comment_create",
        limit=30,
    )

    assert result is None
    assert len(redis.calls) == 1
    assert redis.calls[0]["key"] == (
        f"ds:rl:comment_create:{user_id}"
    )


@pytest.mark.asyncio
async def test_request_at_limit_is_allowed():
    redis = FakeRedis(count=30)

    result = await enforce_rate_limit(
        redis=redis,
        user_id=uuid4(),
        scope="comment_create",
        limit=30,
    )

    assert result is None


@pytest.mark.asyncio
async def test_request_above_limit_is_rejected():
    redis = FakeRedis(count=31, ttl=45)

    with pytest.raises(HTTPException) as error:
        await enforce_rate_limit(
            redis=redis,
            user_id=uuid4(),
            scope="comment_create",
            limit=30,
        )

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "45"
    assert error.value.detail["error"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_redis_failure_returns_503():
    redis = FailingRedis()

    with pytest.raises(HTTPException) as error:
        await enforce_rate_limit(
            redis=redis,
            user_id=uuid4(),
            scope="comment_create",
            limit=30,
        )

    assert error.value.status_code == 503
    assert (
        error.value.detail["error"]["code"]
        == "dependency_unavailable"
    )


@pytest.mark.asyncio
async def test_invalid_limit_is_rejected():
    redis = FakeRedis(count=1)

    with pytest.raises(ValueError):
        await enforce_rate_limit(
            redis=redis,
            user_id=uuid4(),
            scope="comment_create",
            limit=0,
        )