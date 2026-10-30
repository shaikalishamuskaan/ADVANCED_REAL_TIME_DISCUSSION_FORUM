from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.tags import (
    normalize_tag,
    validate_tag,
    normalize_and_validate_tags,
)
from app.domain.validation import (
    validate_thread_input,
    validate_comment_input,
)
from app.domain.policy import can_modify


# -------------------------
# Tag tests
# -------------------------

def test_normalize_tag():
    assert normalize_tag("  Python  ") == "python"


def test_validate_tag():
    assert validate_tag("  Fast-API ") == "fast-api"


@pytest.mark.parametrize(
    "tag",
    ["", " ", "hello world", "tag!", "a" * 31, "UPPER CASE!"],
)
def test_invalid_tag(tag):
    with pytest.raises(ValueError):
        validate_tag(tag)


def test_normalize_and_remove_duplicate_tags():
    result = normalize_and_validate_tags(
        [" Python ", "python", "FastAPI"]
    )

    assert result == ["python", "fastapi"]


def test_maximum_five_tags():
    result = normalize_and_validate_tags(
        ["python", "java", "react", "sql", "fastapi"]
    )

    assert len(result) == 5


def test_more_than_five_tags_fails():
    with pytest.raises(ValueError):
        normalize_and_validate_tags(
            ["python", "java", "react", "sql", "fastapi", "django"]
        )


# -------------------------
# Thread and comment tests
# -------------------------

def test_valid_thread_input():
    validate_thread_input("Learning Python", "A discussion about Python.")


def test_empty_thread_title_fails():
    with pytest.raises(ValueError):
        validate_thread_input("   ", "Description")


def test_thread_title_maximum_length():
    with pytest.raises(ValueError):
        validate_thread_input("a" * 201, "Description")


def test_thread_description_maximum_length():
    with pytest.raises(ValueError):
        validate_thread_input("Title", "a" * 10001)


def test_valid_comment_input():
    validate_comment_input("This is a comment.")


def test_empty_comment_fails():
    with pytest.raises(ValueError):
        validate_comment_input("   ")


def test_comment_maximum_length():
    with pytest.raises(ValueError):
        validate_comment_input("a" * 5001)


# -------------------------
# Permission tests
# -------------------------

def make_actor(user_id, role="member", status="active"):
    return SimpleNamespace(
        user_id=user_id,
        role=role,
        status=status,
    )


def make_resource(author_id, deleted_at=None):
    return SimpleNamespace(
        author_id=author_id,
        deleted_at=deleted_at,
    )


def test_owner_can_modify_own_content():
    user_id = uuid4()

    actor = make_actor(user_id)
    resource = make_resource(user_id)

    assert can_modify(actor, resource) is True


@pytest.mark.parametrize("role", ["moderator", "admin"])
def test_moderator_and_admin_can_modify_others_content(role):
    actor = make_actor(uuid4(), role=role)
    resource = make_resource(uuid4())

    assert can_modify(actor, resource) is True


def test_member_cannot_modify_others_content():
    actor = make_actor(uuid4())
    resource = make_resource(uuid4())

    assert can_modify(actor, resource) is False


def test_disabled_user_cannot_modify_own_content():
    user_id = uuid4()

    actor = make_actor(user_id, status="disabled")
    resource = make_resource(user_id)

    assert can_modify(actor, resource) is False


def test_deleted_content_cannot_be_modified():
    user_id = uuid4()

    actor = make_actor(user_id)
    resource = make_resource(
        user_id,
        deleted_at=datetime.now(timezone.utc),
    )

    assert can_modify(actor, resource) is False