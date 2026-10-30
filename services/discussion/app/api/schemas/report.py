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