from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.write_access import write_access
from app.api.schemas.report import (
    ReportCreateSchema,
    ReportQueueItemSchema,
    ReportQueueResponseSchema,
    ReportResponseSchema,
)

from uuid import UUID

from app.api.schemas.report import (
    ReportActionResponseSchema,
    ReportResolveSchema,
)
from app.services.report_moderation_service import (
    ReportAlreadyProcessedError,
    ReportNotFoundError,
    ReportTargetNotFoundError as ModerationTargetNotFoundError,
    dismiss_report,
    resolve_report,
)
from app.core.database import get_db
from app.core.security import AuthenticatedUser
from app.services.report_service import (
    DuplicateReportError,
    ReportTargetNotFoundError,
    create_report,
)
from app.services.report_queue_service import list_reports


router = APIRouter(
    prefix="/api/forum",
    tags=["Reports"],
)


@router.post(
    "/reports",
    response_model=ReportResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_report_endpoint(
    data: ReportCreateSchema,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("report_create", 10, 3600)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        report = await create_report(
            db,
            reporter_id=current_user.user_id,
            target_type=data.target_type,
            target_id=data.target_id,
            reason=data.reason,
            note=data.note,
        )

    except ReportTargetNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "report_target_not_found",
                    "message": "The content you are trying to report was not found.",
                    "details": {},
                }
            },
        )

    except DuplicateReportError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "duplicate_report",
                    "message": "You have already reported this content.",
                    "details": {},
                }
            },
        )

    return ReportResponseSchema(
        id=report.id,
        status=report.status,
        created_at=report.created_at,
    )


@router.get(
    "/moderation/reports",
    response_model=ReportQueueResponseSchema,
)
async def get_moderation_reports(
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("report_queue", 60)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    report_status: Annotated[
        Literal["open", "resolved", "dismissed"],
        Query(alias="status"),
    ] = "open",
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
):
    # Only moderators and administrators can view the report queue.
    if current_user.role not in ("moderator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "insufficient_role",
                    "message": "Only moderators and administrators can access the report queue.",
                    "details": {},
                }
            },
        )

    try:
        result = await list_reports(
            db,
            report_status=report_status,
            cursor=cursor,
            limit=limit,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "validation_error",
                    "message": "The pagination cursor or query parameters are invalid.",
                    "details": {},
                }
            },
        )

    return ReportQueueResponseSchema(
        items=[
            ReportQueueItemSchema(
                id=report.id,
                reporter_id=report.reporter_id,
                target_type=report.target_type,
                target_id=report.target_id,
                reason=report.reason,
                note=report.note,
                status=report.status,
                created_at=report.created_at,
                resolved_at=report.resolved_at,
            )
            for report in result["items"]
        ],
        next_cursor=result["next_cursor"],
    )

@router.post(
    "/moderation/reports/{report_id}/resolve",
    response_model=ReportActionResponseSchema,
)
async def resolve_moderation_report(
    report_id: UUID,
    data: ReportResolveSchema,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("report_resolve", 30)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ("moderator", "admin"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "insufficient_role",
                    "message": "Only moderators and administrators can resolve reports.",
                    "details": {},
                }
            },
        )

    try:
        report = await resolve_report(
            db,
            report_id=report_id,
            actor_id=current_user.user_id,
            actor_role=current_user.role,
            delete_content=data.action == "delete_content",
        )
    except ReportNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "report_not_found",
                    "message": "Report not found.",
                    "details": {},
                }
            },
        )
    except ReportAlreadyProcessedError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "report_already_processed",
                    "message": "This report has already been processed.",
                    "details": {},
                }
            },
        )
    except ModerationTargetNotFoundError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "report_target_not_found",
                    "message": "The reported content no longer exists or has already been deleted.",
                    "details": {},
                }
            },
        )

    return ReportActionResponseSchema(
        id=report.id,
        status="resolved",
        resolved_at=report.resolved_at,
    )


@router.post(
    "/moderation/reports/{report_id}/dismiss",
    response_model=ReportActionResponseSchema,
)
async def dismiss_moderation_report(
    report_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("report_dismiss", 30)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if current_user.role not in ("moderator", "admin"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": {
                    "code": "insufficient_role",
                    "message": "Only moderators and administrators can dismiss reports.",
                    "details": {},
                }
            },
        )

    try:
        report = await dismiss_report(
            db,
            report_id=report_id,
            actor_id=current_user.user_id,
            actor_role=current_user.role,
        )
    except ReportNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "report_not_found",
                    "message": "Report not found.",
                    "details": {},
                }
            },
        )
    except ReportAlreadyProcessedError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "report_already_processed",
                    "message": "This report has already been processed.",
                    "details": {},
                }
            },
        )

    return ReportActionResponseSchema(
        id=report.id,
        status="dismissed",
        resolved_at=report.resolved_at,
    )