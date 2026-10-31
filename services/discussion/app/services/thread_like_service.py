
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import Outbox
from app.models.thread import Thread
from app.models.thread_like import ThreadLike


async def change_thread_like(
    db: AsyncSession,
    thread_id: UUID,
    user_id: UUID,
    liked: bool,
) -> dict | None:
    try:
        # Lock the thread to prevent concurrent like changes
        # from producing an incorrect like_count.
        thread_result = await db.execute(
            select(Thread)
            .where(
                Thread.id == thread_id,
                Thread.deleted_at.is_(None),
            )
            .with_for_update()
        )

        thread = thread_result.scalar_one_or_none()

        if thread is None:
            await db.rollback()
            return None

        changed = False

        if liked:
            # Insert the like only if it does not already exist.
            statement = (
                insert(ThreadLike)
                .values(
                    user_id=user_id,
                    thread_id=thread_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ThreadLike.user_id,
                        ThreadLike.thread_id,
                    ]
                )
                .returning(ThreadLike.user_id)
            )

            result = await db.execute(statement)
            changed = result.scalar_one_or_none() is not None

            if changed:
                thread.like_count += 1

        else:
            # Delete the like only if it exists.
            statement = (
                delete(ThreadLike)
                .where(
                    ThreadLike.user_id == user_id,
                    ThreadLike.thread_id == thread_id,
                )
                .returning(ThreadLike.user_id)
            )

            result = await db.execute(statement)
            changed = result.scalar_one_or_none() is not None

            if changed:
                thread.like_count = max(0, thread.like_count - 1)

        # Create a live-only event only when the like state changes.
        if changed:
            event_id = uuid.uuid4()
            occurred_at = datetime.now(timezone.utc)

            db.add(
                Outbox(
                    id=event_id,
                    event_type="like.changed",
                    payload={
                        "event_id": str(event_id),
                        "type": "like.changed",
                        "version": 1,
                        "occurred_at": occurred_at.isoformat(),
                        "producer": "discussion",
                        "payload": {
                            "target_type": "thread",
                            "target_id": str(thread_id),
                            "thread_id": str(thread_id),
                            "user_id": str(user_id),
                            "liked": liked,
                            "like_count": thread.like_count,
                        },
                    },
                )
            )

        await db.commit()

        return {
            "liked": liked,
            "like_count": thread.like_count,
            "changed": changed,
        }

    except Exception:
        await db.rollback()
        raise
