from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.thread_like_service import change_thread_like


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, thread, like_change_result):
        self.thread = thread
        self.like_change_result = like_change_result
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.execute_count = 0

    async def execute(self, statement):
        self.execute_count += 1

        if self.execute_count == 1:
            return FakeResult(self.thread)

        return FakeResult(self.like_change_result)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def make_thread(like_count=0):
    return SimpleNamespace(
        id=uuid4(),
        like_count=like_count,
        deleted_at=None,
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_like_increments_count_and_creates_event():
    thread = make_thread(like_count=2)
    user_id = uuid4()
    db = FakeDB(thread, like_change_result=user_id)

    result = await change_thread_like(db, thread.id, user_id, True)

    assert result == {
        "liked": True,
        "like_count": 3,
        "changed": True,
    }
    assert thread.like_count == 3
    assert db.committed is True

    event = next(item for item in db.added if item.event_type == "like.changed")
    assert event.payload["payload"]["target_type"] == "thread"
    assert event.payload["payload"]["liked"] is True
    assert event.payload["payload"]["like_count"] == 3


@pytest.mark.asyncio
async def test_repeated_like_does_not_increment_or_create_event():
    thread = make_thread(like_count=2)
    db = FakeDB(thread, like_change_result=None)

    result = await change_thread_like(db, thread.id, uuid4(), True)

    assert result["liked"] is True
    assert result["like_count"] == 2
    assert result["changed"] is False
    assert thread.like_count == 2
    assert db.added == []
    assert db.committed is True


@pytest.mark.asyncio
async def test_unlike_decrements_count_and_creates_event():
    thread = make_thread(like_count=3)
    user_id = uuid4()
    db = FakeDB(thread, like_change_result=user_id)

    result = await change_thread_like(db, thread.id, user_id, False)

    assert result == {
        "liked": False,
        "like_count": 2,
        "changed": True,
    }
    assert thread.like_count == 2

    event = next(item for item in db.added if item.event_type == "like.changed")
    assert event.payload["payload"]["liked"] is False
    assert event.payload["payload"]["like_count"] == 2


@pytest.mark.asyncio
async def test_repeated_unlike_does_not_decrement_or_create_event():
    thread = make_thread(like_count=2)
    db = FakeDB(thread, like_change_result=None)

    result = await change_thread_like(db, thread.id, uuid4(), False)

    assert result["liked"] is False
    assert result["like_count"] == 2
    assert result["changed"] is False
    assert thread.like_count == 2
    assert db.added == []


@pytest.mark.asyncio
async def test_missing_thread_returns_none():
    db = FakeDB(thread=None, like_change_result=None)

    result = await change_thread_like(db, uuid4(), uuid4(), True)

    assert result is None
    assert db.committed is False
    assert db.added == []