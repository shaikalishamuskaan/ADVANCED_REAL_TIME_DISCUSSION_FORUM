import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.policy import can_modify
from app.models.comment import Comment
from app.models.outbox import Outbox


async def edit_comment(
    db: AsyncSession,
    comment_id: UUID,
    actor_id: UUID,
    actor_role: str,
    body: str,
) -> Comment | None:
    try:
        # 1. Validate the new body.
        cleaned_body = body.strip()

        if not cleaned_body:
            raise ValueError("Comment body cannot be empty.")

        if len(cleaned_body) > 5000:
            raise ValueError("Comment body cannot exceed 5000 characters.")

        # 2. Load the comment and lock it during the update.
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

        # 3. Check whether this actor may modify the comment.
        actor = SimpleNamespace(
            user_id=actor_id,
            role=actor_role,
            status="active",
        )

        if not can_modify(actor, comment):
            await db.rollback()
            raise PermissionError("You cannot edit this comment.")

        # 4. Update the comment.
        now = datetime.now(timezone.utc)
        comment.body = cleaned_body
        comment.updated_at = now

        # 5. Add the comment.updated event to the Outbox.
        event_id = uuid.uuid4()

        db.add(
            Outbox(
                id=event_id,
                event_type="comment.updated",
                payload={
                    "event_id": str(event_id),
                    "type": "comment.updated",
                    "version": 1,
                    "occurred_at": now.isoformat(),
                    "producer": "discussion",
                    "payload": {
                        "comment_id": str(comment.id),
                        "thread_id": str(comment.thread_id),
                        "body": comment.body,
                        "updated_at": now.isoformat(),
                    },
                },
            )
        )

        # 6. Record moderator/admin edits for the audit consumer.
        if actor_id != comment.author_id:
            activity_id = uuid.uuid4()

            action = (
                "comment_edited_by_moderator"
                if actor_role == "moderator"
                else "comment_edited_by_admin"
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

        # 7. Commit the comment and events together.
        await db.commit()
        await db.refresh(comment)

        return comment

    except Exception:
        await db.rollback()
        raise