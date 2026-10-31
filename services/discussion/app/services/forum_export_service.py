from uuid import UUID

from sqlalchemy import and_, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cursor import decode_cursor, encode_cursor
from app.models.comment import Comment
from app.models.tag import Tag
from app.models.thread import Thread
from app.models.thread_tag import ThreadTag


async def export_for_search(
    db: AsyncSession,
    cursor: str | None = None,
    limit: int = 20,
) -> dict:
    if not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50.")

    thread_query = select(
        literal("thread").label("record_type"),
        Thread.id.label("record_id"),
        Thread.created_at.label("created_at"),
        Thread.id.label("thread_id"),
        Thread.author_id.label("author_id"),
        Thread.title.label("title"),
        Thread.description.label("description"),
        literal(None, type_=Comment.body.type).label("body"),
        literal(None, type_=Comment.parent_id.type).label("parent_id"),
        Thread.updated_at.label("updated_at"),
    ).where(Thread.deleted_at.is_(None))

    comment_query = (
        select(
            literal("comment").label("record_type"),
            Comment.id.label("record_id"),
            Comment.created_at.label("created_at"),
            Comment.thread_id.label("thread_id"),
            Comment.author_id.label("author_id"),
            Thread.title.label("title"),
            literal(None, type_=Thread.description.type).label("description"),
            Comment.body.label("body"),
            Comment.parent_id.label("parent_id"),
            Comment.updated_at.label("updated_at"),
        )
        .join(Thread, Thread.id == Comment.thread_id)
        .where(
            Comment.deleted_at.is_(None),
            Thread.deleted_at.is_(None),
        )
    )

    combined = union_all(thread_query, comment_query).subquery()

    statement = select(combined)

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        statement = statement.where(
            or_(
                combined.c.created_at < cursor_created_at,
                and_(
                    combined.c.created_at == cursor_created_at,
                    combined.c.record_id < cursor_id,
                ),
            )
        )

    statement = statement.order_by(
        combined.c.created_at.desc(),
        combined.c.record_id.desc(),
    ).limit(limit + 1)

    result = await db.execute(statement)
    rows = result.mappings().all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    thread_ids = {
        row["thread_id"]
        for row in rows
        if row["record_type"] == "thread"
    }

    tags_by_thread: dict[UUID, list[str]] = {
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
            tags_by_thread[thread_id].append(tag_name)

    items = []

    for row in rows:
        if row["record_type"] == "thread":
            items.append({
                "type": "thread",
                "id": row["record_id"],
                "author_id": row["author_id"],
                "title": row["title"],
                "description": row["description"],
                "tags": tags_by_thread[row["thread_id"]],
                "like_count": None,
                "comment_count": None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        else:
            items.append({
                "type": "comment",
                "id": row["record_id"],
                "thread_id": row["thread_id"],
                "thread_title": row["title"],
                "parent_id": row["parent_id"],
                "author_id": row["author_id"],
                "body": row["body"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })

    next_cursor = None

    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            last["created_at"],
            last["record_id"],
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
    }