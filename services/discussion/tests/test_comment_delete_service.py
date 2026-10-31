from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.comment_delete_service import delete_comment


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, comment):
        self.comment = comment
        self.added = []
        self.executed = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        self.executed.append(statement)
        return FakeResult(self.comment)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        pass


def make_comment(author_id=None, parent_id=None):
    return SimpleNamespace(
        id=uuid4(),
        thread_id=uuid4(),
        author_id=author_id or uuid4(),
        parent_id=parent_id,
        body="Comment to delete",
        reply_count=0,
        updated_at=datetime.now(timezone.utc),
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_author_can_delete_own_comment():
    author_id = uuid4()
    comment = make_comment(author_id=author_id)
    db = FakeDB(comment)

    result = await delete_comment(
        db=db,
        comment_id=comment.id,
        actor_id=author_id,
        actor_role="member",
    )

    assert result.deleted_at is not None
    assert db.committed is True
    assert db.rolled_back is False
    assert [event.event_type for event in db.added] == [
        "comment.deleted"
    ]


@pytest.mark.asyncio
async def test_moderator_deletion_creates_activity_event():
    comment = make_comment()
    db = FakeDB(comment)

    await delete_comment(
        db=db,
        comment_id=comment.id,
        actor_id=uuid4(),
        actor_role="moderator",
    )

    event_types = [event.event_type for event in db.added]

    assert "comment.deleted" in event_types
    assert "activity.recorded" in event_types

    activity = next(
        event for event in db.added
        if event.event_type == "activity.recorded"
    )

    assert activity.payload["payload"]["action"] == (
        "comment_deleted_by_moderator"
    )


@pytest.mark.asyncio
async def test_admin_deletion_creates_activity_event():
    comment = make_comment()
    db = FakeDB(comment)

    await delete_comment(
        db=db,
        comment_id=comment.id,
        actor_id=uuid4(),
        actor_role="admin",
    )

    activity = next(
        event for event in db.added
        if event.event_type == "activity.recorded"
    )

    assert activity.payload["payload"]["actor_role"] == "admin"
    assert activity.payload["payload"]["action"] == (
        "comment_deleted_by_admin"
    )


@pytest.mark.asyncio
async def test_member_cannot_delete_another_users_comment():
    comment = make_comment()
    db = FakeDB(comment)

    with pytest.raises(PermissionError):
        await delete_comment(
            db=db,
            comment_id=comment.id,
            actor_id=uuid4(),
            actor_role="member",
        )

    assert db.committed is False
    assert db.rolled_back is True
    assert db.added == []


@pytest.mark.asyncio
async def test_missing_or_already_deleted_comment_returns_none():
    db = FakeDB(None)

    result = await delete_comment(
        db=db,
        comment_id=uuid4(),
        actor_id=uuid4(),
        actor_role="member",
    )

    assert result is None
    assert db.committed is False
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_deleting_reply_updates_parent_and_thread():
    parent_id = uuid4()
    comment = make_comment(parent_id=parent_id)
    db = FakeDB(comment)

    await delete_comment(
        db=db,
        comment_id=comment.id,
        actor_id=comment.author_id,
        actor_role="member",
    )

    # First query locks the comment; the next two update
    # the parent reply count and thread comment count.
    assert len(db.executed) == 3
    assert db.committed is True


@pytest.mark.asyncio
async def test_deleting_comment_with_replies_keeps_reply_count():
    comment = make_comment()
    comment.reply_count = 2
    db = FakeDB(comment)

    result = await delete_comment(
        db=db,
        comment_id=comment.id,
        actor_id=comment.author_id,
        actor_role="member",
    )

    # The comment is soft-deleted, not physically removed.
    assert result.deleted_at is not None
    assert result.reply_count == 2
    assert db.committed is True