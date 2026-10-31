from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag
from app.models.thread import Thread
from app.models.thread_like import ThreadLike
from app.models.thread_tag import ThreadTag


async def get_thread_details(
    db: AsyncSession,
    thread_id: UUID,
    current_user_id: UUID,
) -> dict | None:
    result = await db.execute(
        select(
            Thread,
            exists().where(
                ThreadLike.thread_id == Thread.id,
                ThreadLike.user_id == current_user_id,
            ).label("liked_by_me"),
        ).where(
            Thread.id == thread_id,
            Thread.deleted_at.is_(None),
        )
    )

    row = result.first()

    if row is None:
        return None

    thread, liked_by_me = row

    tag_result = await db.execute(
        select(Tag.name)
        .join(ThreadTag, ThreadTag.tag_id == Tag.id)
        .where(ThreadTag.thread_id == thread.id)
        .order_by(Tag.name)
    )

    tags = list(tag_result.scalars().all())

    return {
        "thread": thread,
        "liked_by_me": liked_by_me,
        "tags": tags,
    }