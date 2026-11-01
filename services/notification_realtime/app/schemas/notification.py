from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationActor(BaseModel):
    id: UUID
    username: str


class NotificationItem(BaseModel):
    id: UUID
    type: str
    actor: NotificationActor
    thread_id: UUID
    comment_id: UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    next_cursor: str | None


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    message: str
    id: UUID
    read_at: datetime


class MarkAllReadResponse(BaseModel):
    message: str
    updated_count: int