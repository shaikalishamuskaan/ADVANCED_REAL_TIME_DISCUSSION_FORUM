from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.comment_depth import build_comment_structure


@pytest.fixture
def thread_id():
    return uuid4()


def make_comment(
    thread_id,
    depth,
    parent_id=None,
):
    return SimpleNamespace(
        id=uuid4(),
        thread_id=thread_id,
        depth=depth,
        parent_id=parent_id,
    )


def test_top_level_comment(thread_id):
    result = build_comment_structure(
        parent=None,
        thread_id=thread_id,
    )

    assert result.parent_id is None
    assert result.depth == 1
    assert result.is_continuation is False


def test_reply_to_depth_one(thread_id):
    parent = make_comment(thread_id, depth=1)

    result = build_comment_structure(parent, thread_id)

    assert result.parent_id == parent.id
    assert result.depth == 2
    assert result.is_continuation is False


def test_reply_to_depth_two(thread_id):
    depth_one_parent = make_comment(thread_id, depth=1)
    parent = make_comment(
        thread_id,
        depth=2,
        parent_id=depth_one_parent.id,
    )

    result = build_comment_structure(parent, thread_id)

    assert result.parent_id == parent.id
    assert result.depth == 3
    assert result.is_continuation is False


def test_reply_to_depth_three_becomes_continuation(thread_id):
    depth_two_parent = make_comment(thread_id, depth=2)
    depth_three_parent = make_comment(
        thread_id,
        depth=3,
        parent_id=depth_two_parent.id,
    )

    result = build_comment_structure(
        depth_three_parent,
        thread_id,
    )

    assert result.parent_id == depth_two_parent.id
    assert result.depth == 3
    assert result.is_continuation is True


def test_continuation_reply_stays_at_depth_three(thread_id):
    depth_two_parent = make_comment(thread_id, depth=2)

    first_continuation = make_comment(
        thread_id,
        depth=3,
        parent_id=depth_two_parent.id,
    )

    result = build_comment_structure(
        first_continuation,
        thread_id,
    )

    assert result.parent_id == depth_two_parent.id
    assert result.depth == 3
    assert result.is_continuation is True


def test_parent_from_another_thread_is_rejected(thread_id):
    another_thread_id = uuid4()
    parent = make_comment(another_thread_id, depth=1)

    with pytest.raises(ValueError, match="another thread"):
        build_comment_structure(parent, thread_id)


def test_invalid_parent_depth_is_rejected(thread_id):
    parent = make_comment(thread_id, depth=4)

    with pytest.raises(ValueError, match="invalid depth"):
        build_comment_structure(parent, thread_id)


def test_depth_three_without_parent_is_rejected(thread_id):
    parent = make_comment(thread_id, depth=3)

    with pytest.raises(ValueError, match="depth-2 parent"):
        build_comment_structure(parent, thread_id)