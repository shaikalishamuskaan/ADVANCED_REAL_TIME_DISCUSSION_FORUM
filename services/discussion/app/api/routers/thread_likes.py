from typing import Annotated
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser
from app.services.thread_like_service import change_thread_like


router = APIRouter(prefix="/api/forum", tags=["Thread Likes"])


class ThreadLikeResponseSchema(BaseModel):
    liked: bool
    like_count: int


async def update_thread_like(
    thread_id: UUID,
    liked: bool,
    current_user: AuthenticatedUser,
    db: AsyncSession,
    redis: Redis,
):
    result = await change_thread_like(
        db=db,
        thread_id=thread_id,
        user_id=current_user.user_id,
        liked=liked,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "Thread not found.",
                    "details": {},
                }
            },
        )

    if result["changed"]:
        try:
            await redis.delete(f"ds:thread:{thread_id}")
            await redis.incr("ds:threads:ver")
        except RedisError:
            # The database transaction has already committed.
            # Redis failure must not fail the successful request.
            pass

    return ThreadLikeResponseSchema(
        liked=result["liked"],
        like_count=result["like_count"],
    )


@router.put(
    "/threads/{thread_id}/like",
    response_model=ThreadLikeResponseSchema,
)
async def like_thread(
    thread_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("thread_like", 60)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    return await update_thread_like(
        thread_id=thread_id,
        liked=True,
        current_user=current_user,
        db=db,
        redis=redis,
    )


@router.delete(
    "/threads/{thread_id}/like",
    response_model=ThreadLikeResponseSchema,
)
async def unlike_thread(
    thread_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("thread_unlike", 60)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    return await update_thread_like(
        thread_id=thread_id,
        liked=False,
        current_user=current_user,
        db=db,
        redis=redis,
    )