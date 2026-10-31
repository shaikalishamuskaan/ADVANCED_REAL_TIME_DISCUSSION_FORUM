from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cursor import decode_cursor, encode_cursor
from app.models.comment import Comment
from app.models.comment_like import CommentLike
from app.models.thread import Thread


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
REPLY_PREVIEW_SIZE = 3


def _cursor_filter(cursor: str | None):
    if not cursor:
        return None

    created_at, comment_id = decode_cursor(cursor)

    return or_(
        Comment.created_at < created_at,
        and_(
            Comment.created_at == created_at,
            Comment.id < comment_id,
        ),
    )


def _next_cursor(items: list[Comment], limit: int) -> str | None:
    if len(items) <= limit:
        return None

    last_item = items[limit - 1]

    return encode_cursor(last_item.created_at, last_item.id)


def _visible_comment_filter(role: str):
    if role in ("moderator", "admin"):
        return True

    return or_(
        Comment.deleted_at.is_(None),
        Comment.reply_count > 0,
    )


async def _liked_by_user(
    db: AsyncSession,
    comment_id: UUID,
    user_id: UUID,
) -> bool:
    result = await db.execute(
        select(
            exists().where(
                CommentLike.comment_id == comment_id,
                CommentLike.user_id == user_id,
            )
        )
    )
    return bool(result.scalar())


async def _comment_response(
    db: AsyncSession,
    comment: Comment,
    user_id: UUID,
    role: str,
    redis,
    username_cache: dict,
) -> dict:
    deleted = comment.deleted_at is not None

    if deleted:
        author = None
        body = None
    else:
        if comment.author_id not in username_cache:
            from app.clients.author_cache import get_author_profile

            username_cache[comment.author_id] = await get_author_profile(
                redis=redis,
                user_id=comment.author_id,
                fallback_username="unknown",
            )

        author = username_cache[comment.author_id]
        body = comment.body

    return {
        "id": comment.id,
        "thread_id": comment.thread_id,
        "parent_id": comment.parent_id,
        "depth": comment.depth,
        "is_continuation": comment.is_continuation,
        "author": author,
        "body": body,
        "mentions": [],
        "like_count": comment.like_count,
        "liked_by_me": (
            False
            if deleted
            else await _liked_by_user(db, comment.id, user_id)
        ),
        "reply_count": comment.reply_count,
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "deleted": deleted,
    }


async def get_thread_comments(
    db: AsyncSession,
    thread_id: UUID,
    user_id: UUID,
    role: str,
    redis,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict | None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError("Limit must be between 1 and 50.")

    thread_result = await db.execute(
        select(Thread.id).where(
            Thread.id == thread_id,
            Thread.deleted_at.is_(None),
        )
    )

    if thread_result.scalar_one_or_none() is None:
        return None

    conditions = [
        Comment.thread_id == thread_id,
        Comment.parent_id.is_(None),
        _visible_comment_filter(role),
    ]

    cursor_condition = _cursor_filter(cursor)
    if cursor_condition is not None:
        conditions.append(cursor_condition)

    result = await db.execute(
        select(Comment)
        .where(*conditions)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit + 1)
    )

    comments = list(result.scalars().all())
    next_cursor = _next_cursor(comments, limit)
    comments = comments[:limit]

    username_cache = {}
    items = []

    for comment in comments:
        deleted = comment.deleted_at is not None

        if deleted:
            author = None
            body = None
            liked = False
        else:
            if comment.author_id not in username_cache:
                from app.clients.author_cache import get_author_profile

                username_cache[comment.author_id] = (
                    await get_author_profile(
                        redis=redis,
                        user_id=comment.author_id,
                        fallback_username="unknown",
                    )
                )

            author = username_cache[comment.author_id]
            body = comment.body
            liked = await _liked_by_user(
                db,
                comment.id,
                user_id,
            )

        reply_result = await db.execute(
            select(Comment)
            .where(
                Comment.parent_id == comment.id,
                _visible_comment_filter(role),
            )
            .order_by(
                Comment.created_at.desc(),
                Comment.id.desc(),
            )
            .limit(REPLY_PREVIEW_SIZE + 1)
        )

        replies = list(reply_result.scalars().all())
        replies_next_cursor = None

        if len(replies) > REPLY_PREVIEW_SIZE:
            last_preview = replies[REPLY_PREVIEW_SIZE - 1]
            replies_next_cursor = encode_cursor(
                last_preview.created_at,
                last_preview.id,
            )

        reply_previews = [
            {
                "id": reply.id,
                "depth": reply.depth,
                "body": (
                    None
                    if reply.deleted_at is not None
                    else reply.body
                ),
            }
            for reply in replies[:REPLY_PREVIEW_SIZE]
        ]

        items.append(
            {
                "id": comment.id,
                "depth": comment.depth,
                "body": body,
                "author": author,
                "like_count": comment.like_count,
                "liked_by_me": liked,
                "reply_count": comment.reply_count,
                "replies": reply_previews,
                "replies_next_cursor": replies_next_cursor,
                "deleted": deleted,
            }
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


async def get_comment_replies(
    db: AsyncSession,
    comment_id: UUID,
    user_id: UUID,
    role: str,
    redis,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> dict | None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError("Limit must be between 1 and 50.")

    parent_result = await db.execute(
        select(Comment).where(
            Comment.id == comment_id,
            _visible_comment_filter(role),
        )
    )

    parent = parent_result.scalar_one_or_none()

    if parent is None:
        return None

    conditions = [
        Comment.parent_id == comment_id,
        _visible_comment_filter(role),
    ]

    cursor_condition = _cursor_filter(cursor)
    if cursor_condition is not None:
        conditions.append(cursor_condition)

    result = await db.execute(
        select(Comment)
        .where(*conditions)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit + 1)
    )

    comments = list(result.scalars().all())
    next_cursor = _next_cursor(comments, limit)
    comments = comments[:limit]

    username_cache = {}
    items = []

    for comment in comments:
        items.append(
            await _comment_response(
                db=db,
                comment=comment,
                user_id=user_id,
                role=role,
                redis=redis,
                username_cache=username_cache,
            )
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
    }