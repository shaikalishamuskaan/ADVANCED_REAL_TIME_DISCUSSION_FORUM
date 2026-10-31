from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.rate_limit import enforce_rate_limit
from app.api.dependencies.user_status import get_active_user
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser


def write_access(
    scope: str,
    limit: int,
    window_seconds: int = 60,
):
    """
    Build a reusable dependency for secured write endpoints.

    Execution order:
    1. JWT authentication
    2. Redis rate limiting
    3. Current account status and role verification
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
    ) -> AuthenticatedUser:

        # Step 1: Enforce the endpoint-specific rate limit.
        await enforce_rate_limit(
            redis=redis,
            user_id=current_user.user_id,
            scope=scope,
            limit=limit,
            window_seconds=window_seconds,
        )

        # Step 2: Verify current account status and role.
        active_user = await get_active_user(
            current_user=current_user,
            redis=redis,
        )

        return active_user

    return dependency