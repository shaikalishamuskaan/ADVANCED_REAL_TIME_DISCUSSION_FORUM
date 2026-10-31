from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cursor import decode_cursor, encode_cursor
from app.domain.tags import normalize_tag, validate_tag
from app.models.tag import Tag
from app.models.thread import Thread
from app.models.thread_like import ThreadLike
from app.models.thread_tag import ThreadTag


async def list_threads(
    db: AsyncSession,
    current_user_id: UUID,
    tag: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict:
    if not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50.")

    statement = (
        select(
            Thread,
            exists().where(
                ThreadLike.thread_id == Thread.id,
                ThreadLike.user_id == current_user_id,
            ).label("liked_by_me"),
        )
        .where(Thread.deleted_at.is_(None))
        .order_by(Thread.created_at.desc(), Thread.id.desc())
    )

    if tag:
        normalized_tag = normalize_tag(tag)
        validate_tag(normalized_tag)

        statement = statement.where(
            exists().where(
                ThreadTag.thread_id == Thread.id,
                ThreadTag.tag_id == Tag.id,
                Tag.name == normalized_tag,
            )
        )

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)

        statement = statement.where(
            or_(
                Thread.created_at < cursor_created_at,
                (
                    (Thread.created_at == cursor_created_at)
                    & (Thread.id < cursor_id)
                ),
            )
        )

    result = await db.execute(statement.limit(limit + 1))
    rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    thread_ids = [thread.id for thread, _ in rows]

    tag_names_by_thread: dict[UUID, list[str]] = {
        thread_id: [] for thread_id in thread_ids
    }

    if thread_ids:
        tag_result = await db.execute(
            select(ThreadTag.thread_id, Tag.name)
            .join(Tag, Tag.id == ThreadTag.tag_id)
            .where(ThreadTag.thread_id.in_(thread_ids))
            .order_by(Tag.name)
        )

        for thread_id, tag_name in tag_result.all():
            tag_names_by_thread[thread_id].append(tag_name)

    next_cursor = None

    if has_more and rows:
        last_thread = rows[-1][0]
        next_cursor = encode_cursor(
            last_thread.created_at,
            last_thread.id,
        )

    return {
        "items": [
            {
                "thread": thread,
                "liked_by_me": liked_by_me,
                "tags": tag_names_by_thread[thread.id],
            }
            for thread, liked_by_me in rows
        ],
        "next_cursor": next_cursor,
    }