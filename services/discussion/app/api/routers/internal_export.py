from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.service_auth import require_search_service
from app.core.database import get_db
from app.services.forum_export_service import export_for_search


router = APIRouter(
    prefix="/internal/forum",
    tags=["Internal"],
)


@router.get(
    "/export",
    dependencies=[Depends(require_search_service)],
)
async def export_for_search_endpoint(
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
):
    try:
        return await export_for_search(
            db=db,
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
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {
                "code": "dependency_unavailable",
                "message": "Author profiles are unavailable for export.",
                "details": {},
            }},
        ) from exc
