
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.core.database import get_db
from app.core.security import AuthenticatedUser
from app.services.comment_like_service import change_comment_like


router = APIRouter(prefix="/api/forum", tags=["Comment Likes"])


class CommentLikeResponseSchema(BaseModel):
    liked: bool
    like_count: int


async def update_comment_like(
    comment_id: UUID,
    liked: bool,
    current_user: AuthenticatedUser,
    db: AsyncSession,
):
    result = await change_comment_like(
        db=db,
        comment_id=comment_id,
        user_id=current_user.user_id,
        liked=liked,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "Comment not found.",
                    "details": {},
                }
            },
        )

    return CommentLikeResponseSchema(
        liked=result["liked"],
        like_count=result["like_count"],
    )


@router.put(
    "/comments/{comment_id}/like",
    response_model=CommentLikeResponseSchema,
)
async def like_comment(
    comment_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("comment_like", 60)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await update_comment_like(
        comment_id=comment_id,
        liked=True,
        current_user=current_user,
        db=db,
    )


@router.delete(
    "/comments/{comment_id}/like",
    response_model=CommentLikeResponseSchema,
)
async def unlike_comment(
    comment_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("comment_unlike", 60)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await update_comment_like(
        comment_id=comment_id,
        liked=False,
        current_user=current_user,
        db=db,
    )
