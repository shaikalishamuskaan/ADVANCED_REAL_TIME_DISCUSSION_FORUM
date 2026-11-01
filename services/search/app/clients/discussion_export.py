from typing import Annotated, Literal
from uuid import UUID

import httpx
from app.core.observability import correlation_headers
from pydantic import AwareDatetime, BaseModel, Field


class ExportRecord(BaseModel):
    id: UUID
    author_id: UUID
    author_username: str = Field(pattern=r"^[A-Za-z0-9_]{3,30}$")
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ExportThread(ExportRecord):
    type: Literal["thread"]
    title: str = Field(max_length=200)
    description: str
    tags: list[str]


class ExportComment(ExportRecord):
    type: Literal["comment"]
    thread_id: UUID
    thread_title: str
    body: str


class ExportPage(BaseModel):
    items: list[Annotated[ExportThread | ExportComment, Field(discriminator="type")]]
    next_cursor: str | None


class DiscussionExportClient:
    def __init__(self, client: httpx.AsyncClient, service_key: str):
        if not service_key:
            raise ValueError("SEARCH_SERVICE_KEY must match Discussion's Search service key")
        self.client = client
        self.service_key = service_key

    async def pages(self):
        cursor = None
        seen = set()
        while True:
            params = {"limit": 50}
            if cursor:
                params["cursor"] = cursor
            response = await self.client.get(
                "/internal/forum/export", params=params,
                headers={"X-Service-Key": self.service_key, **correlation_headers()},
            )
            response.raise_for_status()
            page = ExportPage.model_validate(response.json())
            if page.next_cursor:
                if not page.items or page.next_cursor in seen:
                    raise ValueError("Discussion export returned a non-advancing cursor")
                seen.add(page.next_cursor)
            yield page
            cursor = page.next_cursor
            if not cursor:
                return
