from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.comment_service import create_comment


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDatabase:
    def __init__(self, thread, parent=None):
        self.thread = thread
        self.parent = parent
        self.added = []
        self.executed = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        self.executed.append(statement)

        # The first SELECT loads the thread.
        if len(self.executed) == 1:
            return FakeResult(self.thread)

        # The second SELECT loads the requested parent.
        if self.parent is not None and len(self.executed) == 2:
            return FakeResult(self.parent)

        return FakeResult(None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_create_top_level_comment():
    thread_id = uuid4()
    author_id = uuid4()

    thread = SimpleNamespace(
    id=thread_id,
    author_id=uuid4(),
    deleted_at=None,
)

    db = FakeDatabase(thread)

    comment = await create_comment(
        db=db,
        thread_id=thread_id,
        author_id=author_id,
        body="Hello discussion",
    )

    assert comment.depth == 1
    assert comment.parent_id is None
    assert comment.is_continuation is False
    assert db.committed is True
    assert len(db.added) == 2

    event = db.added[1]
    assert event.event_type == "comment.created"

    event = db.added[1]

    assert event.event_type == "comment.created"
    assert event.payload["type"] == "comment.created"
    assert event.payload["version"] == 1
    assert event.payload["producer"] == "discussion"

    assert event.payload["event_id"] == str(event.id)
    assert event.payload["event_id"] != str(comment.id)

    assert event.payload["payload"]["comment_id"] == str(comment.id)
    assert event.payload["payload"]["author_id"] == str(author_id)
    assert event.payload["payload"]["thread_author_id"] == str(
        thread.author_id
    )
    assert event.payload["payload"]["parent_id"] is None


@pytest.mark.asyncio
async def test_create_reply():
    thread_id = uuid4()
    author_id = uuid4()

    thread = SimpleNamespace(
    id=thread_id,
    author_id=uuid4(),
    deleted_at=None,
    )

    parent = SimpleNamespace(
        id=uuid4(),
        thread_id=thread_id,
        author_id=uuid4(),
        depth=1,
        parent_id=None,
        deleted_at=None,
    )

    db = FakeDatabase(thread, parent)

    comment = await create_comment(
        db=db,
        thread_id=thread_id,
        author_id=author_id,
        body="This is a reply",
        parent_id=parent.id,
    )

    assert comment.parent_id == parent.id
    assert comment.depth == 2
    assert comment.is_continuation is False
    assert db.committed is True

    event = db.added[1]

    assert event.payload["payload"]["parent_id"] == str(parent.id)
    assert event.payload["payload"]["parent_author_id"] == str(
        parent.author_id
    )
    assert event.payload["payload"]["thread_author_id"] == str(
        thread.author_id
    )


@pytest.mark.asyncio
async def test_thread_not_found():
    db = FakeDatabase(thread=None)

    with pytest.raises(ValueError, match="Thread not found"):
        await create_comment(
            db=db,
            thread_id=uuid4(),
            author_id=uuid4(),
            body="Hello",
        )

    assert db.committed is False


@pytest.mark.asyncio
async def test_parent_not_found():
    thread_id = uuid4()

    thread = SimpleNamespace(
    id=thread_id,
    author_id=uuid4(),
    deleted_at=None,
    )
    db = FakeDatabase(thread=thread, parent=None)

    with pytest.raises(ValueError, match="Parent comment not found"):
        await create_comment(
            db=db,
            thread_id=thread_id,
            author_id=uuid4(),
            body="Hello",
            parent_id=uuid4(),
        )

    assert db.committed is False