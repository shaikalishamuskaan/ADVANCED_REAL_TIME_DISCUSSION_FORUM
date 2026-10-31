from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.api.schemas.common import AuthorSchema
from app.api.schemas.thread import (
    ThreadListResponseSchema,
    ThreadResponseSchema,
)
from app.clients.author_cache import get_author_profile
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser
from app.services.thread_query_service import list_threads


router = APIRouter(prefix="/api/forum", tags=["Threads"])


@router.get(
    "/threads",
    response_model=ThreadListResponseSchema,
)
async def get_threads(
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("thread_list", 60)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    tag: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
):
    try:
        result = await list_threads(
            db=db,
            current_user_id=current_user.user_id,
            tag=tag,
            cursor=cursor,
            limit=limit,
        )
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

    response_items = []

    for item in result["items"]:
        thread = item["thread"]

        profile = await get_author_profile(
            redis=redis,
            user_id=thread.author_id,
            fallback_username="unknown",
        )

        response_items.append(
            ThreadResponseSchema(
                id=thread.id,
                title=thread.title,
                description=thread.description,
                author=AuthorSchema.model_validate(profile),
                tags=item["tags"],
                like_count=thread.like_count,
                liked_by_me=item["liked_by_me"],
                comment_count=thread.comment_count,
                is_edited=thread.updated_at > thread.created_at,
                created_at=thread.created_at,
                updated_at=thread.updated_at,
            )
        )

    return ThreadListResponseSchema(
        items=response_items,
        next_cursor=result["next_cursor"],
    )