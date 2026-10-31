from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.core.database import get_db
from app.core.security import AuthenticatedUser
from app.services.comment_delete_service import delete_comment


router = APIRouter(
    prefix="/api/forum",
    tags=["Comment Deletion"],
)


@router.delete("/comments/{comment_id}")
async def remove_comment(
    comment_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("comment_delete", 30)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        comment = await delete_comment(
            db=db,
            comment_id=comment_id,
            actor_id=current_user.user_id,
            actor_role=current_user.role,
        )

        if comment is None:
            raise HTTPException(
                status_code=404,
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
            "deleted": True,
            "deleted_at": comment.deleted_at,
        }

    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "forbidden",
                    "message": str(exc),
                    "details": {},
                }
            },
        )