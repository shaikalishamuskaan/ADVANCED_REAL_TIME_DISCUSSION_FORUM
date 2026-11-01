import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.notify.workers import cleanup


@pytest.mark.asyncio
@pytest.mark.parametrize('days', [0, -1])
async def test_invalid_retention_never_deletes(days):
    session = AsyncMock()
    with pytest.raises(ValueError, match='positive'):
        await cleanup.cleanup_published_outbox(session, days)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_naive_cleanup_time_never_deletes():
    session = AsyncMock()
    with pytest.raises(ValueError, match='timezone'):
        await cleanup.cleanup_published_outbox(session, 7, datetime(2026, 11, 1))
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_returns_affected_row_count():
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=4)
    assert await cleanup.cleanup_published_outbox(session, 7, datetime(2026, 11, 1, tzinfo=timezone.utc)) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('database_failure,expected_delay', [(False, 86400), (True, 60)])
async def test_worker_commits_or_rolls_back_and_schedules_retry(monkeypatch, database_failure, expected_delay):
    session = AsyncMock()
    transaction = AsyncMock()
    session.begin = MagicMock(return_value=transaction)
    session.execute.return_value = SimpleNamespace(rowcount=2)
    if database_failure:
        session.execute.side_effect = SQLAlchemyError('Unavailable')
    factory_context = AsyncMock()
    factory_context.__aenter__.return_value = session
    monkeypatch.setattr(cleanup, 'AsyncSessionLocal', MagicMock(return_value=factory_context))
    monkeypatch.setattr(cleanup, 'get_settings', lambda: SimpleNamespace(OUTBOX_RETENTION_DAYS=7))
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(cleanup.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await cleanup.run_cleanup_forever()
    sleep.assert_awaited_once_with(expected_delay)
    transaction.__aexit__.assert_awaited_once()
    exception_type = transaction.__aexit__.call_args.args[0]
    assert exception_type is (SQLAlchemyError if database_failure else None)

@pytest.mark.asyncio
async def test_processed_cleanup_rejects_naive_time():
    session = AsyncMock()
    with pytest.raises(ValueError, match='timezone'):
        await cleanup.cleanup_processed_events(session, datetime(2026, 11, 1))
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_processed_cleanup_returns_deleted_count():
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=3)
    assert await cleanup.cleanup_processed_events(session) == 3


@pytest.mark.asyncio
async def test_second_cleanup_failure_rolls_back_whole_worker_transaction(monkeypatch):
    session = AsyncMock()
    transaction = AsyncMock()
    session.begin = MagicMock(return_value=transaction)
    session.execute.side_effect = [SimpleNamespace(rowcount=2), SQLAlchemyError('Second delete failed')]
    context = AsyncMock()
    context.__aenter__.return_value = session
    monkeypatch.setattr(cleanup, 'AsyncSessionLocal', MagicMock(return_value=context))
    monkeypatch.setattr(cleanup, 'get_settings', lambda: SimpleNamespace(OUTBOX_RETENTION_DAYS=7))
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(cleanup.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await cleanup.run_cleanup_forever()
    assert session.execute.await_count == 2
    assert transaction.__aexit__.call_args.args[0] is SQLAlchemyError
    sleep.assert_awaited_once_with(60)
