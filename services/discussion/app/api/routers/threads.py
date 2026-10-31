from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.api.schemas.common import AuthorSchema
from app.api.schemas.thread import (
    ThreadCreateSchema,
    ThreadResponseSchema,
)
from app.clients.author_cache import get_author_profile
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser
from app.models.tag import Tag
from app.models.thread_tag import ThreadTag
from app.services.thread_service import create_thread
from sqlalchemy import select

router = APIRouter(
    prefix="/api/forum",
    tags=["Threads"],
)


@router.post(
    "/threads",
    response_model=ThreadResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread_endpoint(
    request: ThreadCreateSchema,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("thread_create", 10)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    try:
        thread = await create_thread(
            db=db,
            author_id=current_user.user_id,
            author_username=current_user.username,
            title=request.title,
            description=request.description,
            tags=request.tags,
        )

        # Read the tags associated with the newly created thread.
        

        result = await db.execute(
            select(Tag.name)
            .join(ThreadTag, ThreadTag.tag_id == Tag.id)
            .where(ThreadTag.thread_id == thread.id)
            .order_by(Tag.name)
        )
        tag_names = list(result.scalars().all())

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
        )

    profile = await get_author_profile(
        redis=redis,
        user_id=current_user.user_id,
        fallback_username=current_user.username,
    )

    return ThreadResponseSchema(
        id=thread.id,
        title=thread.title,
        description=thread.description,
        author=AuthorSchema.model_validate(profile),
        tags=tag_names,
        like_count=thread.like_count,
        liked_by_me=False,
        comment_count=thread.comment_count,
        is_edited=False,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )