import base64
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.clients.user_profiles import get_user_profiles
from app.core.database import get_db
from app.models.notification import Notification
from app.schemas.notification import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationActor,
    NotificationItem,
    NotificationListResponse,
    UnreadCountResponse,
)

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


def encode_cursor(created_at: datetime, notification_id: UUID) -> str:
    value = f"{created_at.isoformat()}|{notification_id}"
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True).decode()
        timestamp, notification_id = decoded.split("|", 1)

        created_at = datetime.fromisoformat(timestamp)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Cursor timestamp must include a timezone")
        return created_at, UUID(notification_id)

    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail={
            "error": {"code": "invalid_cursor", "message": "Invalid cursor", "details": {}},
        })


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    query = select(Notification).where(
        Notification.recipient_id == current_user["id"]
    )

    if unread:
        query = query.where(Notification.read_at.is_(None))

    if cursor:
        created_at, notification_id = decode_cursor(cursor)

        query = query.where(
            (Notification.created_at < created_at)
            | (
                (Notification.created_at == created_at)
                & (Notification.id < notification_id)
            )
        )

    query = query.order_by(
        Notification.created_at.desc(),
        Notification.id.desc(),
    ).limit(limit + 1)

    result = await session.execute(query)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]

    try:
        profiles = await get_user_profiles(
            [str(row.actor_id) for row in rows]
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=503, detail="Unable to retrieve notification actor details")

    items = []

    for row in rows:
        profile = profiles.get(str(row.actor_id))

        if profile is None:
            raise HTTPException(
                status_code=503,
                detail="Unable to retrieve notification actor details",
            )

        items.append(
            NotificationItem(
                id=row.id,
                type=row.type,
                actor=NotificationActor(
                    id=row.actor_id,
                    username=profile["username"],
                ),
                thread_id=row.thread_id,
                comment_id=row.comment_id,
                read_at=row.read_at,
                created_at=row.created_at,
            )
        )

    next_cursor = None

    if has_more and rows:
        last_row = rows[-1]
        next_cursor = encode_cursor(last_row.created_at, last_row.id)

    return NotificationListResponse(
        items=items,
        next_cursor=next_cursor,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_id == current_user["id"],
            Notification.read_at.is_(None),
        )
    )

    return {"unread_count": result.scalar_one()}


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
async def mark_notification_read(
    notification_id: UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_id == current_user["id"],
        ).with_for_update()
    )

    notification = result.scalar_one_or_none()

    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(notification)

    return {
        "message": "Notification marked as read",
        "id": notification.id,
        "read_at": notification.read_at,
    }


@router.post("/read-all", response_model=MarkAllReadResponse)
async def mark_all_notifications_read(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(
        update(Notification)
        .where(
            Notification.recipient_id == current_user["id"],
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )

    await session.commit()

    return {
        "message": "All notifications marked as read",
        "updated_count": result.rowcount or 0,
    }
