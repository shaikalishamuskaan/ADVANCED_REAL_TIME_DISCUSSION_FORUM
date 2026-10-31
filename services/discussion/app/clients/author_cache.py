import json
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.clients.identity import fetch_user_profiles


AUTHOR_CACHE_TTL_SECONDS = 60


async def get_author_profile(
    redis: Redis,
    user_id: UUID,
    fallback_username: str,
) -> dict:
    cache_key = f"ds:author:{user_id}"

    try:
        cached_profile = await redis.get(cache_key)

        if cached_profile:
            profile = json.loads(cached_profile)

            if isinstance(profile, dict) and {
                "id",
                "username",
                "display_name",
                "avatar_url",
            }.issubset(profile):
                return profile

    except (RedisError, json.JSONDecodeError, TypeError):
        pass

    try:
        profiles = await fetch_user_profiles([str(user_id)])

        if profiles:
            profile = profiles[0]

            try:
                await redis.set(
                    cache_key,
                    json.dumps(profile),
                    ex=AUTHOR_CACHE_TTL_SECONDS,
                )
            except RedisError:
                pass

            return profile

    except RuntimeError:
        pass

    return {
        "id": str(user_id),
        "username": fallback_username,
        "display_name": fallback_username,
        "avatar_url": None,
    }