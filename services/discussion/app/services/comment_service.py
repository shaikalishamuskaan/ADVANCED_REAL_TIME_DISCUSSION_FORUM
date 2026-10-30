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
) -> Comment:

    # 1. Validate the comment body.
    validate_comment_input(body)

    # 2. Find the thread and ensure it is not deleted.
    thread_result = await db.execute(
        select(Thread).where(
            Thread.id == thread_id,
            Thread.deleted_at.is_(None),
        )
    )

    thread = thread_result.scalar_one_or_none()

    if thread is None:
        raise ValueError("Thread not found.")

    # 3. Load the requested parent, if this is a reply.
    parent = None

    if parent_id is not None:
        parent_result = await db.execute(
            select(Comment).where(
                Comment.id == parent_id,
                Comment.deleted_at.is_(None),
            )
        )

        parent = parent_result.scalar_one_or_none()

        if parent is None:
            raise ValueError("Parent comment not found.")

    # 4. Calculate the actual parent and depth.
    structure = build_comment_structure(
        parent=parent,
        thread_id=thread_id,
    )

    # 5. Create the comment.
    comment = Comment(
        thread_id=thread_id,
        author_id=author_id,
        parent_id=structure.parent_id,
        depth=structure.depth,
        is_continuation=structure.is_continuation,
        body=body.strip(),
    )

    db.add(comment)

    # 6. Increment reply_count on the actual stored parent.
    if structure.parent_id is not None:
        await db.execute(
            update(Comment)
            .where(
                Comment.id == structure.parent_id,
                Comment.deleted_at.is_(None),
            )
            .values(reply_count=Comment.reply_count + 1)
        )

    # 7. Increment the thread's comment_count.
    await db.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .values(comment_count=Thread.comment_count + 1)
    )

    # 8. Insert the event into the Outbox.
    outbox_event = Outbox(
        event_type="comment.created",
        payload={
            "event_id": str(comment.id),
            "type": "comment.created",
            "version": 1,
            "producer": "discussion",
            "payload": {
                "comment_id": str(comment.id),
                "thread_id": str(thread_id),
                "author_id": str(author_id),
                "parent_id": (
                    str(structure.parent_id)
                    if structure.parent_id
                    else None
                ),
                "depth": structure.depth,
                "is_continuation": structure.is_continuation,
                "body": comment.body,
            },
        },
    )

    db.add(outbox_event)

    # 9. Commit all database changes together.
    try:
        await db.commit()
        await db.refresh(comment)
    except Exception:
        await db.rollback()
        raise

    return comment