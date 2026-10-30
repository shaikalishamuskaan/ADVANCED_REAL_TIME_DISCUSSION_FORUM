import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import AuthorSchema, MentionSchema


class CommentCreateSchema(BaseModel):
    body: str = Field(max_length=5000)
    parent_id: uuid.UUID | None = None


class CommentResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    parent_id: uuid.UUID | None
    depth: int
    is_continuation: bool
    author: AuthorSchema | None
    body: str | None
    mentions: list[MentionSchema]
    like_count: int
    liked_by_me: bool
    reply_count: int
    created_at: datetime
    updated_at: datetime
    deleted: bool


class CommentReplyPreviewSchema(BaseModel):
    id: uuid.UUID
    depth: int
    body: str | None


class CommentWithRepliesSchema(BaseModel):
    id: uuid.UUID
    depth: int
    body: str | None
    author: AuthorSchema | None
    like_count: int
    liked_by_me: bool
    reply_count: int
    replies: list[CommentReplyPreviewSchema]
    replies_next_cursor: str | None = None
    deleted: bool = False


class CommentPageResponseSchema(BaseModel):
    items: list[CommentWithRepliesSchema]
    next_cursor: str | None = None


class ReplyPageResponseSchema(BaseModel):
    items: list[CommentResponseSchema]
    next_cursor: str | None = None

class CommentCreatedSchema(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    parent_id: uuid.UUID | None
    author_id: uuid.UUID
    depth: int
    is_continuation: bool
    body: str
    like_count: int
    reply_count: int
    created_at: datetime
    updated_at: datetime