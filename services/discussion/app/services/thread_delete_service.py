import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.policy import can_modify
from app.models.outbox import Outbox
from app.models.thread import Thread


async def delete_thread(
    db: AsyncSession,
    thread_id: UUID,
    actor,
) -> datetime | None:
    try:
        result = await db.execute(
            select(Thread)
            .where(
                Thread.id == thread_id,
                Thread.deleted_at.is_(None),
            )
            .with_for_update()
        )
        thread = result.scalar_one_or_none()

        if thread is None:
            return None

        if not can_modify(actor, thread):
            raise PermissionError(
                "You are not allowed to delete this thread."
            )

        now = datetime.now(timezone.utc)
        thread.deleted_at = now
        thread.updated_at = now

        event_id = uuid.uuid4()

        db.add(
            Outbox(
                id=event_id,
                event_type="thread.deleted",
                payload={
                    "event_id": str(event_id),
                    "type": "thread.deleted",
                    "version": 1,
                    "occurred_at": now.isoformat(),
                    "producer": "discussion",
                    "payload": {
                        "thread_id": str(thread.id),
                        "actor_id": str(actor.user_id),
                        "deleted_at": now.isoformat(),
                    },
                },
            )
        )

        # Moderator/admin deletions must also be audited.
        if actor.role in ("moderator", "admin"):
            activity_event_id = uuid.uuid4()

            db.add(
                Outbox(
                    id=activity_event_id,
                    event_type="activity.recorded",
                    payload={
                        "event_id": str(activity_event_id),
                        "type": "activity.recorded",
                        "version": 1,
                        "occurred_at": now.isoformat(),
                        "producer": "discussion",
                        "payload": {
                            "actor_id": str(actor.user_id),
                            "actor_role": actor.role,
                            "action": (
                                "thread_deleted_by_moderator"
                                if actor.role == "moderator"
                                else "thread_deleted_by_admin"
                            ),
                            "target_type": "thread",
                            "target_id": str(thread.id),
                            "metadata": {},
                            "occurred_at": now.isoformat(),
                        },
                    },
                )
            )

        await db.commit()
        return now

    except Exception:
        await db.rollback()
        raise