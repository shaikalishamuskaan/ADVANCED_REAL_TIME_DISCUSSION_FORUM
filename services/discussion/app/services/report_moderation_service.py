import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment
from app.models.outbox import Outbox
from app.models.report import Report
from app.models.thread import Thread


class ReportNotFoundError(Exception):
    pass


class ReportAlreadyProcessedError(Exception):
    pass


class ReportTargetNotFoundError(Exception):
    pass


def _add_outbox_event(
    db: AsyncSession,
    *,
    event_type: str,
    occurred_at: datetime,
    payload: dict,
) -> None:
    event_id = uuid.uuid4()

    envelope = {
        "event_id": str(event_id),
        "type": event_type,
        "version": 1,
        "occurred_at": occurred_at.isoformat(),
        "producer": "discussion",
        "payload": payload,
    }

    db.add(
        Outbox(
            id=event_id,
            event_type=event_type,
            payload=envelope,
        )
    )


def _add_activity_event(
    db: AsyncSession,
    *,
    actor_id: UUID,
    actor_role: str,
    action: str,
    target_type: str,
    target_id: UUID,
    metadata: dict,
    occurred_at: datetime,
) -> None:
    _add_outbox_event(
        db,
        event_type="activity.recorded",
        occurred_at=occurred_at,
        payload={
            "actor_id": str(actor_id),
            "actor_role": actor_role,
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id),
            "metadata": metadata,
            "occurred_at": occurred_at.isoformat(),
        },
    )


async def _delete_reported_content(
    db: AsyncSession,
    *,
    report: Report,
    actor_id: UUID,
    actor_role: str,
    now: datetime,
) -> None:
    if report.target_type == "thread":
        result = await db.execute(
            select(Thread)
            .where(
                Thread.id == report.target_id,
                Thread.deleted_at.is_(None),
            )
            .with_for_update()
        )
        thread = result.scalar_one_or_none()

        if thread is None:
            raise ReportTargetNotFoundError

        thread.deleted_at = now
        thread.updated_at = now

        _add_outbox_event(
            db,
            event_type="thread.deleted",
            occurred_at=now,
            payload={
                "thread_id": str(thread.id),
                "actor_id": str(actor_id),
                "deleted_at": now.isoformat(),
            },
        )

        action = (
            "thread_deleted_by_moderator"
            if actor_role == "moderator"
            else "thread_deleted_by_admin"
        )

        _add_activity_event(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type="thread",
            target_id=thread.id,
            metadata={"report_id": str(report.id)},
            occurred_at=now,
        )

    elif report.target_type == "comment":
        result = await db.execute(
            select(Comment)
            .where(
                Comment.id == report.target_id,
                Comment.deleted_at.is_(None),
            )
            .with_for_update()
        )
        comment = result.scalar_one_or_none()

        if comment is None:
            raise ReportTargetNotFoundError

        comment.deleted_at = now
        comment.updated_at = now

        if comment.parent_id is not None:
            await db.execute(
                update(Comment)
                .where(
                    Comment.id == comment.parent_id,
                    Comment.reply_count > 0,
                )
                .values(reply_count=Comment.reply_count - 1)
            )

        await db.execute(
            update(Thread)
            .where(
                Thread.id == comment.thread_id,
                Thread.comment_count > 0,
            )
            .values(comment_count=Thread.comment_count - 1)
        )

        _add_outbox_event(
            db,
            event_type="comment.deleted",
            occurred_at=now,
            payload={
                "comment_id": str(comment.id),
                "thread_id": str(comment.thread_id),
                "deleted_at": now.isoformat(),
            },
        )

        action = (
            "comment_deleted_by_moderator"
            if actor_role == "moderator"
            else "comment_deleted_by_admin"
        )

        _add_activity_event(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type="comment",
            target_id=comment.id,
            metadata={
                "thread_id": str(comment.thread_id),
                "report_id": str(report.id),
            },
            occurred_at=now,
        )

    else:
        raise ValueError("Invalid report target type.")


async def resolve_report(
    db: AsyncSession,
    *,
    report_id: UUID,
    actor_id: UUID,
    actor_role: str,
    delete_content: bool = False,
) -> Report:
    try:
        result = await db.execute(
            select(Report)
            .where(Report.id == report_id)
            .with_for_update()
        )
        report = result.scalar_one_or_none()

        if report is None:
            raise ReportNotFoundError

        if report.status != "open":
            raise ReportAlreadyProcessedError

        now = datetime.now(timezone.utc)

        if delete_content:
            await _delete_reported_content(
                db,
                report=report,
                actor_id=actor_id,
                actor_role=actor_role,
                now=now,
            )

        report.status = "resolved"
        report.resolved_at = now
        if not delete_content:
            _add_activity_event(
                db,
                actor_id=actor_id,
                actor_role=actor_role,
                action=(
                    "report_resolved_by_moderator"
                    if actor_role == "moderator"
                    else "report_resolved_by_admin"
                ),
                target_type="report",
                target_id=report.id,
                metadata={"delete_content": delete_content},
                occurred_at=now,
            )

        await db.commit()
        await db.refresh(report)

        return report

    except Exception:
        await db.rollback()
        raise


async def dismiss_report(
    db: AsyncSession,
    *,
    report_id: UUID,
    actor_id: UUID,
    actor_role: str,
) -> Report:
    try:
        result = await db.execute(
            select(Report)
            .where(Report.id == report_id)
            .with_for_update()
        )
        report = result.scalar_one_or_none()

        if report is None:
            raise ReportNotFoundError

        if report.status != "open":
            raise ReportAlreadyProcessedError

        now = datetime.now(timezone.utc)

        report.status = "dismissed"
        report.resolved_at = now

        _add_activity_event(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            action=(
                "report_dismissed_by_moderator"
                if actor_role == "moderator"
                else "report_dismissed_by_admin"
            ),
            target_type="report",
            target_id=report.id,
            metadata={},
            occurred_at=now,
        )

        await db.commit()
        await db.refresh(report)

        return report

    except Exception:
        await db.rollback()
        raise