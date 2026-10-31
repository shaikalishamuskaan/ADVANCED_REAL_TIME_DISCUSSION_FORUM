from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.write_access import write_access
from app.core.database import get_db
from app.core.security import AuthenticatedUser
from app.services.tag_deletion_service import delete_tag


router = APIRouter(
    prefix="/api/forum/admin/tags",
    tags=["Admin Tags"],
)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag_endpoint(
    tag_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("tag_delete", 10)),
    ],
    db=Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "forbidden",
                    "message": "Administrator access required.",
                    "details": {},
                }
            },
        )

    deleted = await delete_tag(db=db, tag_id=tag_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "tag_not_found",
                    "message": "Tag not found.",
                    "details": {},
                }
            },
        )

    return None