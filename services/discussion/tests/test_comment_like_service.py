
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.comment_like_service import change_comment_like


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, comment, like_change_result):
        self.comment = comment
        self.like_change_result = like_change_result
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.execute_count = 0

    async def execute(self, statement):
        self.execute_count += 1

        if self.execute_count == 1:
            return FakeResult(self.comment)

        return FakeResult(self.like_change_result)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def make_comment(like_count=0):
    return SimpleNamespace(
        id=uuid4(),
        thread_id=uuid4(),
        like_count=like_count,
        deleted_at=None,
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_like_increments_count_and_creates_event():
    comment = make_comment(like_count=2)
    user_id = uuid4()
    db = FakeDB(comment, like_change_result=user_id)

    result = await change_comment_like(
        db, comment.id, user_id, True
    )

    assert result["liked"] is True
    assert result["like_count"] == 3
    assert result["changed"] is True
    assert result["thread_id"] == comment.thread_id
    assert comment.like_count == 3
    assert db.committed is True

    event = next(
        item for item in db.added
        if item.event_type == "like.changed"
    )
    payload = event.payload["payload"]

    assert payload["target_type"] == "comment"
    assert payload["target_id"] == str(comment.id)
    assert payload["thread_id"] == str(comment.thread_id)
    assert payload["liked"] is True
    assert payload["like_count"] == 3


@pytest.mark.asyncio
async def test_repeated_like_does_not_increment_or_create_event():
    comment = make_comment(like_count=2)
    db = FakeDB(comment, like_change_result=None)

    result = await change_comment_like(
        db, comment.id, uuid4(), True
    )

    assert result["liked"] is True
    assert result["like_count"] == 2
    assert result["changed"] is False
    assert comment.like_count == 2
    assert db.added == []
    assert db.committed is True


@pytest.mark.asyncio
async def test_unlike_decrements_count_and_creates_event():
    comment = make_comment(like_count=3)
    user_id = uuid4()
    db = FakeDB(comment, like_change_result=user_id)

    result = await change_comment_like(
        db, comment.id, user_id, False
    )

    assert result["liked"] is False
    assert result["like_count"] == 2
    assert result["changed"] is True
    assert comment.like_count == 2

    event = next(
        item for item in db.added
        if item.event_type == "like.changed"
    )
    payload = event.payload["payload"]

    assert payload["target_type"] == "comment"
    assert payload["liked"] is False
    assert payload["like_count"] == 2


@pytest.mark.asyncio
async def test_repeated_unlike_does_not_decrement_or_create_event():
    comment = make_comment(like_count=2)
    db = FakeDB(comment, like_change_result=None)

    result = await change_comment_like(
        db, comment.id, uuid4(), False
    )

    assert result["liked"] is False
    assert result["like_count"] == 2
    assert result["changed"] is False
    assert comment.like_count == 2
    assert db.added == []


@pytest.mark.asyncio
async def test_missing_or_deleted_comment_returns_none():
    db = FakeDB(comment=None, like_change_result=None)

    result = await change_comment_like(
        db, uuid4(), uuid4(), True
    )

    assert result is None
    assert db.committed is False
    assert db.added == []
    assert db.rolled_back is True
