import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.policy import can_modify
from app.models.comment import Comment
from app.models.outbox import Outbox
from app.models.thread import Thread


async def delete_comment(
    db: AsyncSession,
    comment_id: UUID,
    actor_id: UUID,
    actor_role: str,
) -> Comment | None:
    try:
        result = await db.execute(
            select(Comment)
            .where(
                Comment.id == comment_id,
                Comment.deleted_at.is_(None),
            )
            .with_for_update()
        )
        comment = result.scalar_one_or_none()

        if comment is None:
            await db.rollback()
            return None

        actor = SimpleNamespace(
            user_id=actor_id,
            role=actor_role,
            status="active",
        )

        if not can_modify(actor, comment):
            await db.rollback()
            raise PermissionError("You cannot delete this comment.")

        now = datetime.now(timezone.utc)

        # Soft-delete the comment.
        comment.deleted_at = now
        comment.updated_at = now

        # Decrement the direct parent's reply count.
        if comment.parent_id is not None:
            await db.execute(
                update(Comment)
                .where(
                    Comment.id == comment.parent_id,
                    Comment.reply_count > 0,
                )
                .values(reply_count=Comment.reply_count - 1)
            )

        # Decrement the thread's active comment count.
        await db.execute(
            update(Thread)
            .where(
                Thread.id == comment.thread_id,
                Thread.comment_count > 0,
            )
            .values(comment_count=Thread.comment_count - 1)
        )

        # Record comment.deleted in the transactional Outbox.
        event_id = uuid.uuid4()

        db.add(
            Outbox(
                id=event_id,
                event_type="comment.deleted",
                payload={
                    "event_id": str(event_id),
                    "type": "comment.deleted",
                    "version": 1,
                    "occurred_at": now.isoformat(),
                    "producer": "discussion",
                    "payload": {
                        "comment_id": str(comment.id),
                        "thread_id": str(comment.thread_id),
                        "deleted_at": now.isoformat(),
                    },
                },
            )
        )

        # Moderation deletions must also be audited.
        if actor_id != comment.author_id:
            activity_id = uuid.uuid4()

            action = (
                "comment_deleted_by_moderator"
                if actor_role == "moderator"
                else "comment_deleted_by_admin"
            )

            db.add(
                Outbox(
                    id=activity_id,
                    event_type="activity.recorded",
                    payload={
                        "event_id": str(activity_id),
                        "type": "activity.recorded",
                        "version": 1,
                        "occurred_at": now.isoformat(),
                        "producer": "discussion",
                        "payload": {
                            "actor_id": str(actor_id),
                            "actor_role": actor_role,
                            "action": action,
                            "target_type": "comment",
                            "target_id": str(comment.id),
                            "metadata": {
                                "thread_id": str(comment.thread_id),
                            },
                            "occurred_at": now.isoformat(),
                        },
                    },
                )
            )

        await db.commit()
        await db.refresh(comment)

        return comment

    except Exception:
        await db.rollback()
        raise