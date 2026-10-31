import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment
from app.models.outbox import Outbox
from app.models.report import Report
from app.models.thread import Thread


class ReportTargetNotFoundError(Exception):
    pass


class DuplicateReportError(Exception):
    pass


async def create_report(
    db: AsyncSession,
    *,
    reporter_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    reason: str,
    note: str | None,
) -> Report:
    # Confirm that the reported content exists and is not deleted.
    if target_type == "thread":
        target = await db.scalar(
            select(Thread).where(
                Thread.id == target_id,
                Thread.deleted_at.is_(None),
            )
        )
    elif target_type == "comment":
        target = await db.scalar(
            select(Comment).where(
                Comment.id == target_id,
                Comment.deleted_at.is_(None),
            )
        )
    else:
        raise ValueError("Invalid report target type")

    if target is None:
        raise ReportTargetNotFoundError

    # Check for an existing report before attempting insertion.
    existing_report = await db.scalar(
        select(Report.id).where(
            Report.reporter_id == reporter_id,
            Report.target_type == target_type,
            Report.target_id == target_id,
        )
    )

    if existing_report is not None:
        raise DuplicateReportError

    report = Report(
        id=uuid.uuid4(),
        reporter_id=reporter_id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        note=note.strip() if note else None,
        status="open",
    )

    db.add(report)

    occurred_at = datetime.now(timezone.utc)

    event_id = uuid.uuid4()
    event_payload = {
        "report_id": str(report.id),
        "target_type": target_type,
        "target_id": str(target_id),
        "reason": reason,
    }

    envelope = {
        "event_id": str(event_id),
        "event_type": "report.created",
        "version": 1,
        "occurred_at": occurred_at.isoformat(),
        "producer": "discussion",
        "payload": event_payload,
    }

    outbox_event = Outbox(
        id=event_id,
        event_type="report.created",
        payload=envelope,
    )

    db.add(outbox_event)

    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        constraint_name = getattr(
            getattr(exc.orig, "diag", None),
            "constraint_name",
            None,
        )

        await db.rollback()

        if constraint_name == "uq_reporter_target":
            raise DuplicateReportError from exc

        raise

    await db.refresh(report)

    return report