import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReportCreateSchema(BaseModel):
    target_type: Literal["thread", "comment"]
    target_id: uuid.UUID
    reason: Literal["spam", "harassment", "off-topic", "other"]
    note: str | None = Field(default=None, max_length=500)


class ReportResponseSchema(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime


class ReportResolvedResponseSchema(BaseModel):
    id: uuid.UUID
    status: str
    resolved_at: datetime

class ReportQueueItemSchema(BaseModel):
    id: uuid.UUID
    reporter_id: uuid.UUID
    target_type: Literal["thread", "comment"]
    target_id: uuid.UUID
    reason: Literal["spam", "harassment", "off-topic", "other"]
    note: str | None = None
    status: Literal["open", "resolved", "dismissed"]
    created_at: datetime
    resolved_at: datetime | None = None


class ReportQueueResponseSchema(BaseModel):
    items: list[ReportQueueItemSchema]
    next_cursor: str | None = None


class ReportResolveSchema(BaseModel):
    action: Literal["delete_content"] | None = None
    note: str | None = Field(default=None, max_length=500)


class ReportActionResponseSchema(BaseModel):
    id: uuid.UUID
    status: Literal["resolved", "dismissed"]
    resolved_at: datetime