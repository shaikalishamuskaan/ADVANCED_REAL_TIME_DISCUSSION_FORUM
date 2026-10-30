import pytest

from app.models import Comment


def test_comment_table_name():
    assert Comment.__tablename__ == "comment"


def test_comment_has_expected_columns():
    expected_columns = {
        "id",
        "thread_id",
        "parent_id",
        "author_id",
        "depth",
        "is_continuation",
        "body",
        "like_count",
        "reply_count",
        "created_at",
        "updated_at",
        "deleted_at",
    }

    actual_columns = set(Comment.__table__.columns.keys())

    assert actual_columns == expected_columns


def test_comment_depth_constraint_exists():
    constraints = {
        constraint.name
        for constraint in Comment.__table__.constraints
    }

    assert "ck_comment_depth_range" in constraints