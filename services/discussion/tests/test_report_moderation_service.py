
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.report_moderation_service import (
    ReportAlreadyProcessedError,
    ReportNotFoundError,
    ReportTargetNotFoundError,
    dismiss_report,
    resolve_report,
)


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, report=None, target=None):
        self.report = report
        self.target = target
        self.added = []
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.refreshed = False
        self.query_count = 0
        self.fail_on_execute = False

    async def execute(self, statement):
        self.executed.append(statement)
        self.query_count += 1

        if self.fail_on_execute:
            raise RuntimeError("Database operation failed")

        if self.query_count == 1:
            return FakeResult(self.report)

        return FakeResult(self.target)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, obj):
        self.refreshed = True


def make_report(target_type="thread", status="open"):
    return SimpleNamespace(
        id=uuid4(),
        target_type=target_type,
        target_id=uuid4(),
        status=status,
        resolved_at=None,
    )


def make_thread():
    return SimpleNamespace(
        id=uuid4(),
        deleted_at=None,
        updated_at=datetime.now(timezone.utc),
    )


def make_comment(parent_id=None):
    return SimpleNamespace(
        id=uuid4(),
        thread_id=uuid4(),
        parent_id=parent_id,
        deleted_at=None,
        updated_at=datetime.now(timezone.utc),
    )


def get_events(db, event_type):
    return [
        event
        for event in db.added
        if event.event_type == event_type
    ]


@pytest.mark.asyncio
async def test_resolve_report_without_deleting_content():
    report = make_report()
    db = FakeDB(report=report)

    result = await resolve_report(
        db,
        report_id=report.id,
        actor_id=uuid4(),
        actor_role="moderator",
    )

    assert result.status == "resolved"
    assert result.resolved_at is not None
    assert db.committed is True
    assert db.rolled_back is False
    assert db.refreshed is True

    assert len(get_events(db, "activity.recorded")) == 1
    assert get_events(db, "thread.deleted") == []


@pytest.mark.asyncio
async def test_resolve_report_with_thread_deletion():
    report = make_report(target_type="thread")
    thread = make_thread()
    report.target_id = thread.id
    db = FakeDB(report=report, target=thread)

    result = await resolve_report(
        db,
        report_id=report.id,
        actor_id=uuid4(),
        actor_role="moderator",
        delete_content=True,
    )

    assert result.status == "resolved"
    assert thread.deleted_at is not None
    assert db.committed is True

    assert len(get_events(db, "thread.deleted")) == 1
    assert len(get_events(db, "activity.recorded")) == 1


@pytest.mark.asyncio
async def test_resolve_report_with_comment_deletion():
    report = make_report(target_type="comment")
    comment = make_comment()
    report.target_id = comment.id
    db = FakeDB(report=report, target=comment)

    result = await resolve_report(
        db,
        report_id=report.id,
        actor_id=uuid4(),
        actor_role="admin",
        delete_content=True,
    )

    assert result.status == "resolved"
    assert comment.deleted_at is not None
    assert db.committed is True

    assert len(get_events(db, "comment.deleted")) == 1
    assert len(get_events(db, "activity.recorded")) == 1


@pytest.mark.asyncio
async def test_resolve_report_with_missing_report_is_rejected():
    db = FakeDB(report=None)

    with pytest.raises(ReportNotFoundError):
        await resolve_report(
            db,
            report_id=uuid4(),
            actor_id=uuid4(),
            actor_role="moderator",
        )

    assert db.committed is False
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_already_processed_report_cannot_be_resolved():
    report = make_report(status="dismissed")
    db = FakeDB(report=report)

    with pytest.raises(ReportAlreadyProcessedError):
        await resolve_report(
            db,
            report_id=report.id,
            actor_id=uuid4(),
            actor_role="moderator",
        )

    assert db.committed is False
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_missing_reported_content_rolls_back_resolution():
    report = make_report(target_type="thread")
    db = FakeDB(report=report, target=None)

    with pytest.raises(ReportTargetNotFoundError):
        await resolve_report(
            db,
            report_id=report.id,
            actor_id=uuid4(),
            actor_role="moderator",
            delete_content=True,
        )

    assert report.status == "open"
    assert db.committed is False
    assert db.rolled_back is True
    assert db.added == []


@pytest.mark.asyncio
async def test_dismiss_report():
    report = make_report()
    db = FakeDB(report=report)

    result = await dismiss_report(
        db,
        report_id=report.id,
        actor_id=uuid4(),
        actor_role="moderator",
    )

    assert result.status == "dismissed"
    assert result.resolved_at is not None
    assert db.committed is True
    assert db.rolled_back is False

    activity = get_events(db, "activity.recorded")
    assert len(activity) == 1
    assert activity[0].payload["payload"]["action"] == (
        "report_dismissed_by_moderator"
    )


@pytest.mark.asyncio
async def test_already_processed_report_cannot_be_dismissed():
    report = make_report(status="resolved")
    db = FakeDB(report=report)

    with pytest.raises(ReportAlreadyProcessedError):
        await dismiss_report(
            db,
            report_id=report.id,
            actor_id=uuid4(),
            actor_role="moderator",
        )

    assert db.committed is False
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_missing_report_cannot_be_dismissed():
    db = FakeDB(report=None)

    with pytest.raises(ReportNotFoundError):
        await dismiss_report(
            db,
            report_id=uuid4(),
            actor_id=uuid4(),
            actor_role="admin",
        )

    assert db.committed is False
    assert db.rolled_back is True


@pytest.mark.asyncio
async def test_database_failure_rolls_back_resolution():
    report = make_report()
    db = FakeDB(report=report)
    db.fail_on_execute = True

    with pytest.raises(RuntimeError):
        await resolve_report(
            db,
            report_id=report.id,
            actor_id=uuid4(),
            actor_role="moderator",
        )

    assert db.committed is False
    assert db.rolled_back is True
