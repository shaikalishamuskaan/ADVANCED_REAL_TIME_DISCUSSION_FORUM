from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.thread_detail_service import get_thread_details


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeResult:
    def __init__(self, row=None, values=None):
        self.row = row
        self.values = values or []

    def first(self):
        return self.row

    def scalars(self):
        return FakeScalarResult(self.values)


class FakeDatabase:
    def __init__(self, results):
        self.results = iter(results)

    async def execute(self, statement):
        return next(self.results)


@pytest.mark.asyncio
async def test_get_thread_details_returns_thread_and_tags():
    thread_id = uuid4()
    author_id = uuid4()
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    thread = SimpleNamespace(
        id=thread_id,
        author_id=author_id,
        title="Python discussion",
        description="Discuss Python",
        like_count=5,
        comment_count=3,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )

    db = FakeDatabase(
        [
            FakeResult(row=(thread, True)),
            FakeResult(values=["python", "web-development"]),
        ]
    )

    result = await get_thread_details(
        db=db,
        thread_id=thread_id,
        current_user_id=user_id,
    )

    assert result is not None
    assert result["thread"] == thread
    assert result["liked_by_me"] is True
    assert result["tags"] == ["python", "web-development"]


@pytest.mark.asyncio
async def test_get_thread_details_returns_none_when_missing():
    db = FakeDatabase([FakeResult(row=None)])

    result = await get_thread_details(
        db=db,
        thread_id=uuid4(),
        current_user_id=uuid4(),
    )

    assert result is None