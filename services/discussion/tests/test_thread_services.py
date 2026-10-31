from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.thread_service import create_thread


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return FakeScalarResult(self.values)


class FakeDatabase:
    def __init__(self, existing_tags=None):
        self.existing_tags = existing_tags or []
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        return FakeResult(self.existing_tags)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        pass

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_create_thread_without_tags():
    author_id = uuid4()
    db = FakeDatabase()

    thread = await create_thread(
        db=db,
        author_id=author_id,
        author_username="test_user",
        title="Discussion title",
        description="Discussion description",
        tags=[],
    )

    assert thread.author_id == author_id
    assert thread.title == "Discussion title"
    assert thread.description == "Discussion description"
    assert thread.like_count == 0
    assert thread.comment_count == 0
    assert db.committed is True
    assert db.rolled_back is False

    outbox = [
        item for item in db.added
        if getattr(item, "event_type", None) == "thread.created"
    ]
    assert len(outbox) == 1
    assert outbox[0].payload["event_id"] == str(outbox[0].id)
    assert outbox[0].payload["payload"]["thread_id"] == str(thread.id)


@pytest.mark.asyncio
async def test_create_thread_normalizes_and_creates_tags():
    db = FakeDatabase()

    thread = await create_thread(
        db=db,
        author_id=uuid4(),
        author_username="test_user",
        title="  My Thread  ",
        description="  Thread description  ",
        tags=["Python", " FASTAPI ", "python"],
    )

    assert thread.title == "My Thread"
    assert thread.description == "Thread description"

    created_tags = [
        item for item in db.added
        if item.__class__.__name__ == "Tag"
    ]
    assert {tag.name for tag in created_tags} == {
        "python",
        "fastapi",
    }

    links = [
        item for item in db.added
        if item.__class__.__name__ == "ThreadTag"
    ]
    assert len(links) == 2
    assert db.committed is True


@pytest.mark.asyncio
async def test_create_thread_reuses_existing_tag():
    existing_tag = SimpleNamespace(
        id=uuid4(),
        name="python",
    )
    db = FakeDatabase(existing_tags=[existing_tag])

    await create_thread(
        db=db,
        author_id=uuid4(),
        author_username="test_user",
        title="Python discussion",
        description="Existing tag test",
        tags=["python"],
    )

    created_tags = [
        item for item in db.added
        if item.__class__.__name__ == "Tag"
    ]
    links = [
        item for item in db.added
        if item.__class__.__name__ == "ThreadTag"
    ]

    assert created_tags == []
    assert len(links) == 1
    assert links[0].tag_id == existing_tag.id


@pytest.mark.asyncio
async def test_create_thread_rejects_invalid_tag():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        await create_thread(
            db=db,
            author_id=uuid4(),
            author_username="test_user",
            title="Valid title",
            description="Valid description",
            tags=["invalid tag!"],
        )

    assert db.committed is False
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_create_thread_rejects_empty_title():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        await create_thread(
            db=db,
            author_id=uuid4(),
            author_username="test_user",
            title="   ",
            description="Description",
            tags=[],
        )

    assert db.committed is False
    assert db.rolled_back is True