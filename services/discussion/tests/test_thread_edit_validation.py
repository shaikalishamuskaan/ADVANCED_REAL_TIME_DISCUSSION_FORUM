from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.schemas.thread import ThreadUpdateSchema
from app.domain.policy import can_modify


def test_update_schema_accepts_title_only():
    request = ThreadUpdateSchema(title="Updated title")

    assert request.title == "Updated title"
    assert request.description is None
    assert request.tags is None


def test_update_schema_accepts_empty_tags():
    request = ThreadUpdateSchema(tags=[])

    assert request.tags == []


def test_update_schema_rejects_empty_request():
    with pytest.raises(ValidationError):
        ThreadUpdateSchema()


def test_update_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ThreadUpdateSchema(unknown_field="value")


def test_author_can_edit_own_thread():
    user_id = uuid4()

    actor = SimpleNamespace(
        user_id=user_id,
        role="member",
        status="active",
    )
    thread = SimpleNamespace(
        author_id=user_id,
        deleted_at=None,
    )

    assert can_modify(actor, thread) is True


@pytest.mark.parametrize("role", ["moderator", "admin"])
def test_moderator_and_admin_can_edit_other_threads(role):
    actor = SimpleNamespace(
        user_id=uuid4(),
        role=role,
        status="active",
    )
    thread = SimpleNamespace(
        author_id=uuid4(),
        deleted_at=None,
    )

    assert can_modify(actor, thread) is True


def test_member_cannot_edit_another_users_thread():
    actor = SimpleNamespace(
        user_id=uuid4(),
        role="member",
        status="active",
    )
    thread = SimpleNamespace(
        author_id=uuid4(),
        deleted_at=None,
    )

    assert can_modify(actor, thread) is False


def test_deleted_thread_cannot_be_modified():
    actor = SimpleNamespace(
        user_id=uuid4(),
        role="admin",
        status="active",
    )
    thread = SimpleNamespace(
        author_id=uuid4(),
        deleted_at="2026-10-31T10:00:00Z",
    )

    assert can_modify(actor, thread) is False