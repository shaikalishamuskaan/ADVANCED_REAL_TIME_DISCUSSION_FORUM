import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.comment_depth import build_comment_structure
from app.domain.validation import validate_comment_input
from app.models.comment import Comment
from app.models.outbox import Outbox
from app.models.thread import Thread


async def create_comment(
    db: AsyncSession,
    thread_id: UUID,
    author_id: UUID,
    body: str,
    parent_id: UUID | None = None,
    author_username: str = "",
) -> Comment:

    try:
        # 1. Validate the body.
        validate_comment_input(body)

        # 2. Find the active thread.
        thread_result = await db.execute(
            select(Thread).where(
                Thread.id == thread_id,
                Thread.deleted_at.is_(None),
            )
        )

        thread = thread_result.scalar_one_or_none()

        if thread is None:
            raise ValueError("Thread not found.")

        # 3. Load the originally requested parent.
        parent = None

        if parent_id is not None:
            parent_result = await db.execute(
                select(Comment).where(Comment.id == parent_id)
            )

            parent = parent_result.scalar_one_or_none()

            if parent is None:
                raise ValueError("Parent comment not found.")

            if parent.deleted_at is not None:
                raise ValueError("Cannot reply to a deleted comment.")

        # 4. Calculate the actual stored parent and depth.
        structure = build_comment_structure(
            parent=parent,
            thread_id=thread_id,
        )

        # 5. Create the comment.
        now = datetime.now(timezone.utc)

        comment = Comment(
            id=uuid.uuid4(),
            thread_id=thread_id,
            author_id=author_id,
            parent_id=structure.parent_id,
            depth=structure.depth,
            is_continuation=structure.is_continuation,
            body=body.strip(),
            created_at=now,
            updated_at=now,
        )

        db.add(comment)

        # 6. Increment the reply count of the actual stored parent.
        if structure.parent_id is not None:
            await db.execute(
                update(Comment)
                .where(
                    Comment.id == structure.parent_id,
                    Comment.deleted_at.is_(None),
                )
                .values(reply_count=Comment.reply_count + 1)
            )

        # 7. Increment the thread comment count.
        await db.execute(
            update(Thread)
            .where(
                Thread.id == thread_id,
                Thread.deleted_at.is_(None),
            )
            .values(comment_count=Thread.comment_count + 1)
        )

        # 8. Create the Outbox row with its own event ID.
        outbox_id = uuid.uuid4()

        outbox_event = Outbox(
            id=outbox_id,
            event_type="comment.created",
            payload={
                "event_id": str(outbox_id),
                "type": "comment.created",
                "version": 1,
                "occurred_at": now.isoformat(),
                "producer": "discussion",
                "payload": {
                    "comment_id": str(comment.id),
                    "thread_id": str(thread_id),
                    "parent_id": (
                        str(structure.parent_id)
                        if structure.parent_id is not None
                        else None
                    ),
                    "author_id": str(author_id),
                    "author_username": author_username,
                    "body": comment.body,
                    "depth": structure.depth,
                    "parent_author_id": (
                        str(parent.author_id)
                        if parent is not None
                        else None
                    ),
                    "thread_author_id": str(thread.author_id),
                    "created_at": now.isoformat(),
                },
            },
        )

        db.add(outbox_event)

        # 9. Commit comment, counters, and Outbox together.
        await db.commit()
        await db.refresh(comment)

        return comment

    except Exception:
        await db.rollback()
        raise