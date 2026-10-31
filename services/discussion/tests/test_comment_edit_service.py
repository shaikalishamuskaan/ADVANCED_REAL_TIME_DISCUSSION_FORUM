from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.comment_edit_service import edit_comment


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, comment):
        self.comment = comment
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        return FakeResult(self.comment)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        pass


def make_comment(author_id=None):
    return SimpleNamespace(
        id=uuid4(),
        thread_id=uuid4(),
        author_id=author_id or uuid4(),
        body="Old comment",
        updated_at=datetime.now(timezone.utc),
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_author_can_edit_own_comment():
    author_id = uuid4()
    comment = make_comment(author_id)
    db = FakeDB(comment)

    result = await edit_comment(
        db=db,
        comment_id=comment.id,
        actor_id=author_id,
        actor_role="member",
        body="Updated comment",
    )

    assert result.body == "Updated comment"
    assert db.committed is True
    assert db.rolled_back is False

    event_types = [event.event_type for event in db.added]
    assert event_types == ["comment.updated"]


@pytest.mark.asyncio
async def test_moderator_can_edit_another_users_comment():
    comment = make_comment()
    moderator_id = uuid4()
    db = FakeDB(comment)

    await edit_comment(
        db=db,
        comment_id=comment.id,
        actor_id=moderator_id,
        actor_role="moderator",
        body="Moderator edit",
    )

    event_types = [event.event_type for event in db.added]

    assert "comment.updated" in event_types
    assert "activity.recorded" in event_types
    assert db.committed is True


@pytest.mark.asyncio
async def test_admin_can_edit_another_users_comment():
    comment = make_comment()
    admin_id = uuid4()
    db = FakeDB(comment)

    await edit_comment(
        db=db,
        comment_id=comment.id,
        actor_id=admin_id,
        actor_role="admin",
        body="Admin edit",
    )

    activity_event = next(
        event for event in db.added
        if event.event_type == "activity.recorded"
    )

    assert activity_event.payload["payload"]["actor_role"] == "admin"
    assert activity_event.payload["payload"]["action"] == "comment_edited_by_admin"


@pytest.mark.asyncio
async def test_member_cannot_edit_another_users_comment():
    comment = make_comment()
    db = FakeDB(comment)

    with pytest.raises(PermissionError):
        await edit_comment(
            db=db,
            comment_id=comment.id,
            actor_id=uuid4(),
            actor_role="member",
            body="Unauthorized edit",
        )

    assert db.committed is False
    assert db.rolled_back is True
    assert db.added == []


@pytest.mark.asyncio
async def test_deleted_or_missing_comment_returns_none():
    db = FakeDB(None)

    result = await edit_comment(
        db=db,
        comment_id=uuid4(),
        actor_id=uuid4(),
        actor_role="member",
        body="Updated comment",
    )

    assert result is None
    assert db.rolled_back is True
    assert db.committed is False


@pytest.mark.asyncio
async def test_empty_comment_body_is_rejected():
    comment = make_comment()
    db = FakeDB(comment)

    with pytest.raises(ValueError, match="cannot be empty"):
        await edit_comment(
            db=db,
            comment_id=comment.id,
            actor_id=comment.author_id,
            actor_role="member",
            body="   ",
        )

    assert db.committed is False
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_comment_body_over_5000_characters_is_rejected():
    comment = make_comment()
    db = FakeDB(comment)

    with pytest.raises(ValueError, match="5000"):
        await edit_comment(
            db=db,
            comment_id=comment.id,
            actor_id=comment.author_id,
            actor_role="member",
            body="a" * 5001,
        )

    assert db.committed is False
    assert db.rolled_back is True