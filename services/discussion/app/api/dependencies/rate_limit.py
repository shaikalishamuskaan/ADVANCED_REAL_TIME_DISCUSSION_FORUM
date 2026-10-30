from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.dependencies.auth import get_current_user
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser


# Redis executes this script atomically.
# This prevents simultaneous requests from incorrectly
# creating or resetting the rate-limit counter.
RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])

if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end

local remaining = redis.call('TTL', KEYS[1])

return {current, remaining}
"""


async def enforce_rate_limit(
    redis: Redis,
    user_id: UUID,
    scope: str,
    limit: int,
    window_seconds: int = 60,
) -> None:
    """
    Enforce a fixed-window rate limit for one user and API scope.
    """

    if limit < 1 or window_seconds < 1:
        raise ValueError("Limit and window must be positive.")

    key = f"ds:rl:{scope}:{user_id}"

    try:
        result = await redis.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            window_seconds,
        )

        request_count = int(result[0])
        remaining_seconds = int(result[1])

    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "dependency_unavailable",
                    "message": "Rate-limiting service is unavailable.",
                    "details": {},
                }
            },
        )

    if request_count > limit:
        retry_after = max(remaining_seconds, 1)

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "rate_limited",
                    "message": "Too many requests. Please try again later.",
                    "details": {},
                }
            },
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(
    scope: str,
    limit: int,
    window_seconds: int = 60,
):
    """
    Create a reusable FastAPI dependency for a rate limit.
    """

    async def dependency(
        current_user: Annotated[
            AuthenticatedUser,
            Depends(get_current_user),
        ],
        redis: Annotated[
            Redis,
            Depends(get_redis),
        ],
    ) -> None:
        await enforce_rate_limit(
            redis=redis,
            user_id=current_user.user_id,
            scope=scope,
            limit=limit,
            window_seconds=window_seconds,
        )

    return dependency