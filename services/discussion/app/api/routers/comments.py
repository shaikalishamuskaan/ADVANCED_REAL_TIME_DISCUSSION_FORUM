from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.comment import (
    CommentCreateSchema,
    CommentCreatedSchema,
)
from app.core.database import get_db
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
    db: AsyncSession = Depends(get_db),
):
    # Temporary development identity.
    # JWT authentication will replace this before the endpoint is exposed.
    author_id = UUID("11111111-1111-4111-8111-111111111111")

    try:
        comment = await create_comment(
            db=db,
            thread_id=thread_id,
            author_id=author_id,
            body=request.body,
            parent_id=request.parent_id,
        )

        return comment

    except ValueError as exc:
        message = str(exc)

        if message in ("Thread not found.", "Parent comment not found."):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=message,
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )