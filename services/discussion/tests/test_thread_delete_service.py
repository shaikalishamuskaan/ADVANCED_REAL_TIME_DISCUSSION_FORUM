from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.thread_delete_service import delete_thread


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, thread):
        self.thread = thread
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        return FakeResult(self.thread)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_author_can_delete_own_thread():
    author_id = uuid4()
    thread = SimpleNamespace(
        id=uuid4(),
        author_id=author_id,
        deleted_at=None,
        updated_at=None,
    )
    actor = SimpleNamespace(
        user_id=author_id,
        role="member",
        status="active",
    )
    db = FakeDB(thread)

    deleted_at = await delete_thread(db, thread.id, actor)

    assert deleted_at is not None
    assert thread.deleted_at == deleted_at
    assert thread.updated_at == deleted_at
    assert db.committed is True
    assert db.rolled_back is False

    events = [item for item in db.added if item.event_type == "thread.deleted"]
    assert len(events) == 1
    assert events[0].payload["payload"]["thread_id"] == str(thread.id)
    assert events[0].payload["payload"]["actor_id"] == str(author_id)


@pytest.mark.asyncio
async def test_member_cannot_delete_another_users_thread():
    thread = SimpleNamespace(
        id=uuid4(),
        author_id=uuid4(),
        deleted_at=None,
        updated_at=None,
    )
    actor = SimpleNamespace(
        user_id=uuid4(),
        role="member",
        status="active",
    )
    db = FakeDB(thread)

    with pytest.raises(PermissionError):
        await delete_thread(db, thread.id, actor)

    assert db.committed is False
    assert db.rolled_back is True
    assert thread.deleted_at is None


@pytest.mark.asyncio
async def test_moderator_deletion_creates_activity_event():
    thread = SimpleNamespace(
        id=uuid4(),
        author_id=uuid4(),
        deleted_at=None,
        updated_at=None,
    )
    actor = SimpleNamespace(
        user_id=uuid4(),
        role="moderator",
        status="active",
    )
    db = FakeDB(thread)

    await delete_thread(db, thread.id, actor)

    event_types = [item.event_type for item in db.added]
    assert event_types.count("thread.deleted") == 1
    assert event_types.count("activity.recorded") == 1

    activity = next(
        item for item in db.added
        if item.event_type == "activity.recorded"
    )
    assert activity.payload["payload"]["actor_role"] == "moderator"
    assert activity.payload["payload"]["target_id"] == str(thread.id)


@pytest.mark.asyncio
async def test_admin_deletion_creates_activity_event():
    thread = SimpleNamespace(
        id=uuid4(),
        author_id=uuid4(),
        deleted_at=None,
        updated_at=None,
    )
    actor = SimpleNamespace(
        user_id=uuid4(),
        role="admin",
        status="active",
    )
    db = FakeDB(thread)

    await delete_thread(db, thread.id, actor)

    activity = next(
        item for item in db.added
        if item.event_type == "activity.recorded"
    )
    assert activity.payload["payload"]["actor_role"] == "admin"
    assert activity.payload["payload"]["action"] == "thread_deleted_by_admin"


@pytest.mark.asyncio
async def test_missing_or_already_deleted_thread_returns_none():
    actor = SimpleNamespace(
        user_id=uuid4(),
        role="admin",
        status="active",
    )
    db = FakeDB(None)

    result = await delete_thread(db, uuid4(), actor)

    assert result is None
    assert db.committed is False
    assert db.added == []