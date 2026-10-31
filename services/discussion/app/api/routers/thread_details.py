from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.api.schemas.common import AuthorSchema
from app.api.schemas.thread import ThreadResponseSchema
from app.clients.author_cache import get_author_profile
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser
from app.services.thread_detail_service import get_thread_details


router = APIRouter(prefix="/api/forum", tags=["Threads"])


@router.get(
    "/threads/{thread_id}",
    response_model=ThreadResponseSchema,
)
async def get_thread_details_endpoint(
    thread_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("thread_detail", 120)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    result = await get_thread_details(
        db=db,
        thread_id=thread_id,
        current_user_id=current_user.user_id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "thread_not_found",
                    "message": "Thread not found.",
                    "details": {},
                }
            },
        )

    thread = result["thread"]

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
        tags=result["tags"],
        like_count=thread.like_count,
        liked_by_me=result["liked_by_me"],
        comment_count=thread.comment_count,
        is_edited=thread.updated_at > thread.created_at,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )