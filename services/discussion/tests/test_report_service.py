
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.report_service import (
    DuplicateReportError,
    ReportTargetNotFoundError,
    create_report,
)


class FakeDB:
    def __init__(self, target, existing_report=None):
        self.target = target
        self.existing_report = existing_report
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.refreshed = False
        self.query_count = 0

    async def scalar(self, statement):
        self.query_count += 1

        # First query checks whether the target exists.
        if self.query_count == 1:
            return self.target

        # Second query checks for an existing report.
        return self.existing_report

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        self.refreshed = True


def make_target():
    return SimpleNamespace(
        id=uuid4(),
        deleted_at=None,
    )


def get_report_event(db):
    return next(
        item
        for item in db.added
        if getattr(item, "event_type", None) == "report.created"
    )


@pytest.mark.asyncio
async def test_member_can_report_thread():
    reporter_id = uuid4()
    target = make_target()
    db = FakeDB(target)

    result = await create_report(
        db,
        reporter_id=reporter_id,
        target_type="thread",
        target_id=target.id,
        reason="spam",
        note="Repeated promotional content.",
    )

    assert result.reporter_id == reporter_id
    assert result.target_type == "thread"
    assert result.target_id == target.id
    assert result.reason == "spam"
    assert result.note == "Repeated promotional content."
    assert result.status == "open"

    assert db.committed is True
    assert db.rolled_back is False
    assert db.refreshed is True

    event = get_report_event(db)

    assert event.payload["event_type"] == "report.created"
    assert event.payload["payload"]["report_id"] == str(result.id)


@pytest.mark.asyncio
async def test_member_can_report_comment():
    target = make_target()
    db = FakeDB(target)

    result = await create_report(
        db,
        reporter_id=uuid4(),
        target_type="comment",
        target_id=target.id,
        reason="harassment",
        note=None,
    )

    assert result.target_type == "comment"
    assert result.reason == "harassment"
    assert result.note is None
    assert result.status == "open"
    assert db.committed is True


@pytest.mark.asyncio
async def test_reporting_nonexistent_target_is_rejected():
    db = FakeDB(None)

    with pytest.raises(ReportTargetNotFoundError):
        await create_report(
            db,
            reporter_id=uuid4(),
            target_type="thread",
            target_id=uuid4(),
            reason="spam",
            note=None,
        )

    assert db.committed is False
    assert db.added == []


@pytest.mark.asyncio
async def test_duplicate_report_is_rejected():
    target = make_target()
    db = FakeDB(
        target,
        existing_report=uuid4(),
    )

    with pytest.raises(DuplicateReportError):
        await create_report(
            db,
            reporter_id=uuid4(),
            target_type="thread",
            target_id=target.id,
            reason="spam",
            note=None,
        )

    assert db.committed is False
    assert db.added == []


@pytest.mark.asyncio
async def test_report_note_is_trimmed():
    target = make_target()
    db = FakeDB(target)

    result = await create_report(
        db,
        reporter_id=uuid4(),
        target_type="comment",
        target_id=target.id,
        reason="other",
        note="  Please review this content.  ",
    )

    assert result.note == "Please review this content."
    assert db.committed is True


@pytest.mark.asyncio
async def test_report_created_event_contains_required_payload():
    target = make_target()
    db = FakeDB(target)

    result = await create_report(
        db,
        reporter_id=uuid4(),
        target_type="thread",
        target_id=target.id,
        reason="off-topic",
        note=None,
    )

    event = get_report_event(db)
    payload = event.payload["payload"]

    assert payload == {
        "report_id": str(result.id),
        "target_type": "thread",
        "target_id": str(target.id),
        "reason": "off-topic",
    }
