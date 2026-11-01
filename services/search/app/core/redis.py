from redis.asyncio import Redis

from app.core.config import get_settings

redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global redis_client

    if redis_client is None:
        settings = get_settings()

        redis_client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=5,
            health_check_interval=30,
        )

    return redis_client


async def close_redis_client():
    global redis_client

    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None