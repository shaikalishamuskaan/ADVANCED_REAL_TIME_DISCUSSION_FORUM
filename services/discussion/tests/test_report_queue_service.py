from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.cursor import decode_cursor
from app.services.report_queue_service import list_reports


class FakeResult:
    def __init__(self, reports):
        self.reports = reports

    def scalars(self):
        return self

    def all(self):
        return self.reports


class FakeDB:
    def __init__(self, reports):
        self.reports = reports
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.reports)


def make_report(created_at=None, report_status="open"):
    return SimpleNamespace(
        id=uuid4(),
        reporter_id=uuid4(),
        target_type="thread",
        target_id=uuid4(),
        reason="spam",
        note=None,
        status=report_status,
        created_at=created_at or datetime.now(timezone.utc),
        resolved_at=None,
    )


@pytest.mark.asyncio
async def test_list_reports_returns_reports_and_no_next_cursor():
    reports = [make_report(), make_report()]
    db = FakeDB(reports)

    result = await list_reports(db)

    assert result["items"] == reports
    assert result["next_cursor"] is None
    assert db.statement is not None
    assert "report.status" in str(db.statement)


@pytest.mark.asyncio
async def test_list_reports_creates_next_cursor_when_more_results_exist():
    reports = [
        make_report(datetime.now(timezone.utc) - timedelta(minutes=index))
        for index in range(3)
    ]
    db = FakeDB(reports)

    result = await list_reports(db, limit=2)

    assert result["items"] == reports[:2]
    assert result["next_cursor"] is not None

    cursor_created_at, cursor_id = decode_cursor(result["next_cursor"])

    assert cursor_created_at == reports[1].created_at
    assert cursor_id == reports[1].id


@pytest.mark.asyncio
async def test_list_reports_accepts_status_filter():
    reports = [make_report(report_status="resolved")]
    db = FakeDB(reports)

    result = await list_reports(db, report_status="resolved")

    assert result["items"] == reports
    assert "report.status" in str(db.statement)


@pytest.mark.asyncio
async def test_list_reports_rejects_invalid_status():
    db = FakeDB([])

    with pytest.raises(ValueError, match="Invalid report status"):
        await list_reports(db, report_status="pending")


@pytest.mark.asyncio
async def test_list_reports_rejects_invalid_limit():
    db = FakeDB([])

    with pytest.raises(ValueError, match="Limit must be between"):
        await list_reports(db, limit=51)


@pytest.mark.asyncio
async def test_list_reports_rejects_invalid_cursor():
    db = FakeDB([])

    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        await list_reports(db, cursor="invalid-cursor")