from fastapi import Depends, HTTPException
from redis.exceptions import RedisError

from app.api.dependencies.auth import get_current_user
from app.core.redis import get_redis_client

RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {current, redis.call('TTL', KEYS[1])}
"""


async def enforce_search_limit(redis, key: str):
    try:
        current, ttl = await redis.eval(RATE_LIMIT_SCRIPT, 1, key, 60)
    except RedisError:
        raise HTTPException(status_code=503, detail={"error": {
            "code": "dependency_unavailable", "message": "Rate-limiting service is unavailable", "details": {},
        }})
    if int(current) > 30:
        raise HTTPException(status_code=429, detail={"error": {
            "code": "rate_limited", "message": "Too many search requests", "details": {},
        }}, headers={"Retry-After": str(max(int(ttl), 1))})


async def search_access(current_user: dict = Depends(get_current_user)) -> dict:
    await enforce_search_limit(
        get_redis_client(), f"se:rl:search:{current_user['id']}",
    )
    return current_user
