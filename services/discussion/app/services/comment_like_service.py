
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment
from app.models.comment_like import CommentLike
from app.models.outbox import Outbox


async def change_comment_like(
    db: AsyncSession,
    comment_id: UUID,
    user_id: UUID,
    liked: bool,
) -> dict | None:
    try:
        # Lock the comment so concurrent like changes cannot
        # corrupt its like_count.
        comment_result = await db.execute(
            select(Comment)
            .where(
                Comment.id == comment_id,
                Comment.deleted_at.is_(None),
            )
            .with_for_update()
        )

        comment = comment_result.scalar_one_or_none()

        if comment is None:
            await db.rollback()
            return None

        changed = False

        if liked:
            # Insert only if this user has not already liked the comment.
            statement = (
                insert(CommentLike)
                .values(
                    user_id=user_id,
                    comment_id=comment_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        CommentLike.user_id,
                        CommentLike.comment_id,
                    ]
                )
                .returning(CommentLike.user_id)
            )

            result = await db.execute(statement)
            changed = result.scalar_one_or_none() is not None

            if changed:
                comment.like_count += 1

        else:
            # Delete only if this user's like exists.
            statement = (
                delete(CommentLike)
                .where(
                    CommentLike.user_id == user_id,
                    CommentLike.comment_id == comment_id,
                )
                .returning(CommentLike.user_id)
            )

            result = await db.execute(statement)
            changed = result.scalar_one_or_none() is not None

            if changed:
                comment.like_count = max(0, comment.like_count - 1)

        # Create an Outbox event only when the like state changes.
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
                            "target_type": "comment",
                            "target_id": str(comment_id),
                            "thread_id": str(comment.thread_id),
                            "user_id": str(user_id),
                            "liked": liked,
                            "like_count": comment.like_count,
                        },
                    },
                )
            )

        await db.commit()

        return {
            "liked": liked,
            "like_count": comment.like_count,
            "changed": changed,
            "thread_id": comment.thread_id,
        }

    except Exception:
        await db.rollback()
        raise
