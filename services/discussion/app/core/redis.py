from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    settings = get_settings()

    return Redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


async def get_redis() -> Redis:
    return get_redis_client()