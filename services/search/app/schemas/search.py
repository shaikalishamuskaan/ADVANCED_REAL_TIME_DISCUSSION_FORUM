from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    q: str = Field(min_length=2, max_length=100)
    type: Literal["all", "thread", "comment"] = "all"
    tag: str | None = Field(default=None, max_length=30, pattern=r"^[a-z0-9_-]+$")
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("q")
    @classmethod
    def require_two_non_space_characters(cls, value):
        if sum(not character.isspace() for character in value) < 2:
            raise ValueError("Query needs at least two non-space characters")
        return value

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_tag(cls, value):
        return value.strip().lower() or None if isinstance(value, str) else value


class SearchItem(BaseModel):
    type: Literal["thread", "comment"]
    id: UUID
    thread_id: UUID
    title: str | None
    thread_title: str
    snippet: str
    author_username: str
    created_at: datetime


class SearchResponse(BaseModel):
    items: list[SearchItem]
    next_cursor: str | None
