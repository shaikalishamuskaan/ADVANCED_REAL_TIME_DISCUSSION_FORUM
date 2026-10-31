from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.cursor import decode_cursor
from app.services.comment_query_service import (
    get_comment_replies,
    get_thread_comments,
)


class FakeScalarResult:
    def __init__(self, values=None):
        self.values = values or []

    def all(self):
        return self.values


class FakeResult:
    def __init__(self, value=None, values=None):
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self):
        return self.value

    def scalar(self):
        return self.value

    def scalars(self):
        return FakeScalarResult(self.values)


class FakeDatabase:
    def __init__(self, results):
        self.results = iter(results)

    async def execute(self, statement):
        return next(self.results)


class FakeRedis:
    async def get(self, key):
        return None

    async def set(self, *args, **kwargs):
        return True


@pytest.mark.asyncio
async def test_thread_comments_returns_first_page(monkeypatch):
    from app.clients import author_cache

    async def fake_author_profile(**kwargs):
        return {
            "id": str(kwargs["user_id"]),
            "username": "testuser",
            "display_name": "Test User",
            "avatar_url": None,
        }

    monkeypatch.setattr(
        author_cache,
        "get_author_profile",
        fake_author_profile,
    )

    thread_id = uuid4()
    user_id = uuid4()
    author_id = uuid4()
    now = datetime.now(timezone.utc)

    thread = SimpleNamespace(id=thread_id)

    comment = SimpleNamespace(
        id=uuid4(),
        thread_id=thread_id,
        parent_id=None,
        author_id=author_id,
        depth=1,
        is_continuation=False,
        body="Hello",
        like_count=2,
        reply_count=0,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )

    db = FakeDatabase([
        FakeResult(value=thread_id),
        FakeResult(values=[comment]),
        FakeResult(value=False),
        FakeResult(values=[]),
    ])

    result = await get_thread_comments(
        db=db,
        thread_id=thread_id,
        user_id=user_id,
        role="member",
        redis=FakeRedis(),
    )

    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == comment.id
    assert result["items"][0]["body"] == "Hello"
    assert result["items"][0]["liked_by_me"] is False
    assert result["items"][0]["replies"] == []
    assert result["next_cursor"] is None


@pytest.mark.asyncio
async def test_thread_comments_returns_none_for_missing_thread():
    db = FakeDatabase([FakeResult(value=None)])

    result = await get_thread_comments(
        db=db,
        thread_id=uuid4(),
        user_id=uuid4(),
        role="member",
        redis=FakeRedis(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_thread_comments_rejects_invalid_limit():
    with pytest.raises(ValueError, match="Limit"):
        await get_thread_comments(
            db=FakeDatabase([]),
            thread_id=uuid4(),
            user_id=uuid4(),
            role="member",
            redis=FakeRedis(),
            limit=100,
        )


@pytest.mark.asyncio
async def test_replies_returns_none_for_missing_parent():
    db = FakeDatabase([FakeResult(value=None)])

    result = await get_comment_replies(
        db=db,
        comment_id=uuid4(),
        user_id=uuid4(),
        role="member",
        redis=FakeRedis(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_replies_rejects_invalid_limit():
    with pytest.raises(ValueError, match="Limit"):
        await get_comment_replies(
            db=FakeDatabase([]),
            comment_id=uuid4(),
            user_id=uuid4(),
            role="member",
            redis=FakeRedis(),
            limit=0,
        )