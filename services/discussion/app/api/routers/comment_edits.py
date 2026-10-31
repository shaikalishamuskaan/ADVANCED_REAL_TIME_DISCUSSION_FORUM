from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.api.schemas.comment import CommentUpdateSchema
from app.core.database import get_db
from app.core.security import AuthenticatedUser
from app.services.comment_edit_service import edit_comment

router = APIRouter(
    prefix="/api/forum",
    tags=["Comment Editing"],
)


@router.patch("/comments/{comment_id}")
async def update_comment(
    comment_id: UUID,
    request: CommentUpdateSchema,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("comment_edit", 30)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        comment = await edit_comment(
            db=db,
            comment_id=comment_id,
            actor_id=current_user.user_id,
            actor_role=current_user.role,
            body=request.body,
        )

        if comment is None:
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

        return {
            "id": comment.id,
            "thread_id": comment.thread_id,
            "parent_id": comment.parent_id,
            "body": comment.body,
            "updated_at": comment.updated_at,
        }

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
        )