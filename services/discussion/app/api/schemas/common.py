import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuthorSchema(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    avatar_url: str | None = None


class MentionSchema(BaseModel):
    user_id: uuid.UUID
    username: str


class CursorPageSchema(BaseModel):
    next_cursor: str | None = None