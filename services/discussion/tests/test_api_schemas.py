import uuid

import pytest
from pydantic import ValidationError

from app.api.schemas import (
    ThreadCreateSchema,
    CommentCreateSchema,
    ReportCreateSchema,
)


def test_valid_thread_creation():
    thread = ThreadCreateSchema(
        title="Learning FastAPI",
        description="Let's discuss FastAPI.",
        tags=["python", "fastapi"],
    )

    assert thread.title == "Learning FastAPI"
    assert len(thread.tags) == 2


def test_thread_title_maximum_length():
    with pytest.raises(ValidationError):
        ThreadCreateSchema(
            title="A" * 201,
            description="Description",
            tags=[],
        )


def test_thread_description_maximum_length():
    with pytest.raises(ValidationError):
        ThreadCreateSchema(
            title="Valid title",
            description="A" * 10001,
            tags=[],
        )


def test_thread_maximum_five_tags():
    with pytest.raises(ValidationError):
        ThreadCreateSchema(
            title="Valid title",
            description="Description",
            tags=["a", "b", "c", "d", "e", "f"],
        )


def test_valid_top_level_comment():
    comment = CommentCreateSchema(
        body="This is a comment.",
    )

    assert comment.body == "This is a comment."
    assert comment.parent_id is None


def test_valid_reply_comment():
    parent_id = uuid.uuid4()

    comment = CommentCreateSchema(
        body="This is a reply.",
        parent_id=parent_id,
    )

    assert comment.parent_id == parent_id


def test_comment_body_maximum_length():
    with pytest.raises(ValidationError):
        CommentCreateSchema(body="A" * 5001)


def test_valid_report():
    report = ReportCreateSchema(
        target_type="comment",
        target_id=uuid.uuid4(),
        reason="harassment",
        note="Personal insult.",
    )

    assert report.target_type == "comment"
    assert report.reason == "harassment"


def test_invalid_report_reason():
    with pytest.raises(ValidationError):
        ReportCreateSchema(
            target_type="thread",
            target_id=uuid.uuid4(),
            reason="invalid_reason",
        )


def test_invalid_report_target_type():
    with pytest.raises(ValidationError):
        ReportCreateSchema(
            target_type="post",
            target_id=uuid.uuid4(),
            reason="spam",
        )


def test_report_note_maximum_length():
    with pytest.raises(ValidationError):
        ReportCreateSchema(
            target_type="thread",
            target_id=uuid.uuid4(),
            reason="spam",
            note="A" * 501,
        )