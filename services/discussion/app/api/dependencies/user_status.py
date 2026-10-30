import json
from typing import Annotated

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.dependencies.auth import get_current_user
from app.clients.identity import fetch_user_status
from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser


async def get_active_user(
    current_user: Annotated[
        AuthenticatedUser,
        Depends(get_current_user),
    ],
    redis: Annotated[
        Redis,
        Depends(get_redis),
    ],
) -> AuthenticatedUser:

    settings = get_settings()

    cache_key = f"ds:user_status:{current_user.user_id}"

    try:
        cached_data = await redis.get(cache_key)

        if cached_data:
            user_data = json.loads(cached_data)

        else:
            try:
                user_data = await fetch_user_status(
                    str(current_user.user_id)
                )
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={
                        "error": {
                            "code": "unauthenticated",
                            "message": "User account could not be verified.",
                            "details": {},
                        }
                    },
                )
            except RuntimeError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": {
                            "code": "dependency_unavailable",
                            "message": "Identity Service is unavailable.",
                            "details": {},
                        }
                    },
                )

            await redis.set(
                cache_key,
                json.dumps(user_data),
                ex=settings.STATUS_CACHE_TTL_SECONDS,
            )

    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "dependency_unavailable",
                    "message": "Redis is unavailable.",
                    "details": {},
                }
            },
        )

    if user_data.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "account_disabled",
                    "message": "Your account is disabled.",
                    "details": {},
                }
            },
        )

    return AuthenticatedUser(
        user_id=current_user.user_id,
        username=user_data["username"],
        role=user_data["role"],
    )