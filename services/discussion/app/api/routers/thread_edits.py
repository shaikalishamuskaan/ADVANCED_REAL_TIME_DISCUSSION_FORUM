from types import SimpleNamespace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import exists, select

from app.api.dependencies.write_access import write_access
from app.api.schemas.common import AuthorSchema
from app.api.schemas.thread import ThreadResponseSchema, ThreadUpdateSchema
from app.clients.author_cache import get_author_profile
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser
from app.services.thread_edit_service import edit_thread
from app.models.thread_like import ThreadLike
from app.models.thread import Thread

router = APIRouter(prefix="/api/forum", tags=["Threads"])


@router.patch(
    "/threads/{thread_id}",
    response_model=ThreadResponseSchema,
)
async def edit_thread_endpoint(
    thread_id: UUID,
    request: ThreadUpdateSchema,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("thread_edit", 30)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    # write_access has already verified the account is active.
    # Add status for the existing can_modify policy.
    actor = SimpleNamespace(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role,
        status="active",
    )

    try:
        result = await edit_thread(
            db=db,
            thread_id=thread_id,
            actor=actor,
            title=request.title,
            description=request.description,
            tags=request.tags,
        )

    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "forbidden",
                    "message": str(exc),
                    "details": {},
                }
            },
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "validation_error",
                    "message": str(exc),
                    "details": {},
                }
            },
        ) from exc

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

    thread, tag_names = result
    like_result = await db.execute(
    select(
        exists().where(
            ThreadLike.thread_id == thread.id,
            ThreadLike.user_id == current_user.user_id,
            )
        )
    )
    liked_by_me = bool(like_result.scalar_one())

    # Invalidate the detail cache and advance the list cache version.
    # Redis failures must not turn a committed database update into an error.
    try:
        await redis.delete(f"ds:thread:{thread.id}")
        await redis.incr("ds:threads:ver")
    except RedisError:
        pass

    profile = await get_author_profile(
        redis=redis,
        user_id=thread.author_id,
        fallback_username="unknown",
    )

    return ThreadResponseSchema(
        id=thread.id,
        title=thread.title,
        description=thread.description,
        author=AuthorSchema.model_validate(profile),
        tags=tag_names,
        like_count=thread.like_count,
        liked_by_me=liked_by_me,
        comment_count=thread.comment_count,
        is_edited=thread.updated_at > thread.created_at,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )