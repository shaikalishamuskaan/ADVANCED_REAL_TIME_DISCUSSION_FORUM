import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import AuthorSchema


class ThreadCreateSchema(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(max_length=10000)
    tags: list[str] = Field(max_length=5)


class ThreadResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    author: AuthorSchema
    tags: list[str]
    like_count: int
    liked_by_me: bool
    comment_count: int
    is_edited: bool
    created_at: datetime
    updated_at: datetime


class ThreadListResponseSchema(BaseModel):
    items: list[ThreadResponseSchema]
    next_cursor: str | None = None


class ThreadUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    tags: list[str] | None = Field(default=None, max_length=5)

    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        if all(
            value is None
            for value in (self.title, self.description, self.tags)
        ):
            raise ValueError("Provide at least one field to update.")

        return self