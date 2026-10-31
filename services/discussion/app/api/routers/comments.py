from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.api.schemas.comment import (
    CommentCreateSchema,
    CommentCreatedSchema,
)
from app.api.schemas.common import AuthorSchema
from app.clients.author_cache import get_author_profile
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser
from app.services.comment_service import create_comment


router = APIRouter(
    prefix="/api/forum",
    tags=["Comments"],
)


@router.post(
    "/threads/{thread_id}/comments",
    response_model=CommentCreatedSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread_comment(
    thread_id: UUID,
    request: CommentCreateSchema,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("comment_create", 30)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    try:
        # Create the comment using the authenticated JWT identity.
        comment = await create_comment(
            db=db,
            thread_id=thread_id,
            author_id=current_user.user_id,
            author_username=current_user.username,
            body=request.body,
            parent_id=request.parent_id,
        )

    except ValueError as exc:
        message = str(exc)

        if message == "Thread not found.":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "not_found",
                        "message": message,
                        "details": {},
                    }
                },
            )

        if message == "Parent comment not found.":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "not_found",
                        "message": message,
                        "details": {},
                    }
                },
            )

        if message == "Cannot reply to a deleted comment.":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "unprocessable",
                        "message": message,
                        "details": {},
                    }
                },
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "validation_error",
                    "message": message,
                    "details": {},
                }
            },
        )

    # Retrieve the profile after the database transaction commits.
    profile = await get_author_profile(
        redis=redis,
        user_id=current_user.user_id,
        fallback_username=current_user.username,
    )

    return CommentCreatedSchema(
        id=comment.id,
        thread_id=comment.thread_id,
        parent_id=comment.parent_id,
        depth=comment.depth,
        is_continuation=comment.is_continuation,
        author=AuthorSchema.model_validate(profile),
        body=comment.body,
        mentions=[],
        like_count=comment.like_count,
        liked_by_me=False,
        reply_count=comment.reply_count,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        deleted=comment.deleted_at is not None,
    )