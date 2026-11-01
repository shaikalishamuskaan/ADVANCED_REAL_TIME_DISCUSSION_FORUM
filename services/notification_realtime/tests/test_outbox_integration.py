import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from redis.exceptions import ConnectionError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import get_settings
from app.core.redis import close_redis_client, get_redis_client
from app.models.outbox import Outbox
from app.models.processed_event import ProcessedEvent
from app.models.notification import Notification
from app.notify.workers import outbox_relay as relay
from tests.test_outbox_relay import make_row

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get('RUN_OUTBOX_INTEGRATION') != '1', reason='Set RUN_OUTBOX_INTEGRATION=1; requires local PostgreSQL and Redis'),
]


@pytest_asyncio.fixture
async def infrastructure():
    # All test rows live in a random schema; application tables are untouched.
    schema = f'test_notify_outbox_{uuid4().hex}'
    engine = create_async_engine(
        get_settings().DATABASE_URL,
        execution_options={'schema_translate_map': {None: schema}},
    )
    redis = get_redis_client()
    created = False
    try:
        assert await redis.ping()
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            await connection.run_sync(Outbox.__table__.create)
            await connection.run_sync(ProcessedEvent.__table__.create)
            await connection.run_sync(Notification.__table__.create)
        created = True
        yield engine, redis
    finally:
        if created:
            async with engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()
        await close_redis_client()


async def save_rows(engine, *rows):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add_all(rows)


async def subscribe(redis, channel):
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    async with asyncio.timeout(3):
        while True:
            message = await pubsub.get_message(timeout=0.1)
            if message and message['type'] == 'subscribe':
                return pubsub


async def receive(pubsub):
    async with asyncio.timeout(3):
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message:
                return json.loads(message['data'])


async def test_real_publication_marks_row_published(infrastructure):
    engine, redis = infrastructure
    row = make_row()
    await save_rows(engine, row)
    pubsub = await subscribe(redis, row.payload['target'])
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            assert await relay.publish_pending_batch(session, redis, 100) == 1
        assert await receive(pubsub) == row.payload['event']
        async with AsyncSession(engine) as session:
            saved = await session.get(Outbox, row.id)
            assert saved.published_at is not None
    finally:
        await pubsub.aclose()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        assert await relay.publish_pending_batch(session, redis, 100) == 0


async def test_redis_outage_keeps_rows_for_retry(infrastructure):
    engine, redis = infrastructure
    row = make_row()
    await save_rows(engine, row)
    failing = AsyncMock()
    failing.publish.side_effect = ConnectionError('Simulated Redis outage')
    async with AsyncSession(engine, expire_on_commit=False) as session:
        with pytest.raises(ConnectionError):
            await relay.publish_pending_batch(session, failing, 100)
    async with AsyncSession(engine) as session:
        assert (await session.get(Outbox, row.id)).published_at is None
    async with AsyncSession(engine, expire_on_commit=False) as session:
        # Zero subscribers still counts as successful delivery to Redis.
        assert await relay.publish_pending_batch(session, redis, 100) == 1


async def test_restart_after_publish_repeats_same_message(infrastructure, monkeypatch):
    engine, redis = infrastructure
    row = make_row()
    await save_rows(engine, row)
    pubsub = await subscribe(redis, row.payload['target'])
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            # Simulate losing PostgreSQL after Redis accepted the publication.
            from sqlalchemy.sql.dml import Update
            real_execute = session.execute
            async def fail_marking(statement, *args, **kwargs):
                if isinstance(statement, Update):
                    raise SQLAlchemyError('Connection lost before marking')
                return await real_execute(statement, *args, **kwargs)
            monkeypatch.setattr(session, 'execute', fail_marking)
            with pytest.raises(SQLAlchemyError):
                await relay.publish_pending_batch(session, redis, 100)
        first = await receive(pubsub)
        async with AsyncSession(engine) as session:
            assert (await session.get(Outbox, row.id)).published_at is None
        async with AsyncSession(engine, expire_on_commit=False) as session:
            assert await relay.publish_pending_batch(session, redis, 100) == 1
        assert await receive(pubsub) == first == row.payload['event']
    finally:
        await pubsub.aclose()


async def test_uncommitted_outbox_row_rolls_back(infrastructure):
    engine, redis = infrastructure
    async with AsyncSession(engine) as session:
        session.add(make_row())
        await session.flush()
        await session.rollback()
    async with AsyncSession(engine) as session:
        assert await session.scalar(select(func.count()).select_from(Outbox)) == 0


async def test_single_leader_and_takeover_after_shutdown(infrastructure, monkeypatch):
    engine, redis = infrastructure
    monkeypatch.setattr(relay, 'engine', engine)
    monkeypatch.setattr(relay, 'get_redis_client', lambda: redis)
    monkeypatch.setattr(relay, 'get_settings', lambda: SimpleNamespace(OUTBOX_RELAY_INTERVAL_MS=5, OUTBOX_BATCH_SIZE=100))
    monkeypatch.setattr(relay, 'ADVISORY_LOCK_KEY', uuid4().int % (2**63))
    seen = set()
    async def record_batch(session, client, size):
        seen.add(asyncio.current_task().get_name())
        return 0
    monkeypatch.setattr(relay, 'publish_pending_batch', record_batch)
    first = asyncio.create_task(relay.run_outbox_relay(), name='first-relay')
    second = None
    try:
        async with asyncio.timeout(3):
            while 'first-relay' not in seen:
                await asyncio.sleep(0.005)
        second = asyncio.create_task(relay.run_outbox_relay(), name='second-relay')
        await asyncio.sleep(0.05)
        assert seen == {'first-relay'}
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        async with asyncio.timeout(3):
            while 'second-relay' not in seen:
                await asyncio.sleep(0.005)
    finally:
        tasks = [task for task in (first, second) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

async def test_creation_order_and_batch_limit_with_real_rows(infrastructure):
    from datetime import datetime, timezone
    from uuid import UUID
    engine, redis = infrastructure
    created = datetime.now(timezone.utc)
    first = make_row(id=UUID(int=1), created_at=created)
    second = make_row(id=UUID(int=2), created_at=created)
    second.payload['target'] = first.payload['target']
    await save_rows(engine, second, first)
    pubsub = await subscribe(redis, first.payload['target'])
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            assert await relay.publish_pending_batch(session, redis, 1) == 1
        assert await receive(pubsub) == first.payload['event']
        async with AsyncSession(engine) as session:
            assert (await session.get(Outbox, first.id)).published_at is not None
            assert (await session.get(Outbox, second.id)).published_at is None
        async with AsyncSession(engine, expire_on_commit=False) as session:
            assert await relay.publish_pending_batch(session, redis, 1) == 1
        assert await receive(pubsub) == second.payload['event']
    finally:
        await pubsub.aclose()

@pytest.mark.parametrize('retention_days', [7, 3])
async def test_cleanup_retains_unpublished_recent_and_boundary_rows(infrastructure, retention_days):
    from datetime import datetime, timedelta, timezone
    from app.notify.workers.cleanup import cleanup_published_outbox
    engine, redis = infrastructure
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    old = make_row(published_at=cutoff - timedelta(microseconds=1))
    boundary = make_row(published_at=cutoff)
    recent = make_row(published_at=cutoff + timedelta(microseconds=1))
    unpublished = make_row(created_at=now - timedelta(days=100))
    recently_published_old_row = make_row(created_at=now - timedelta(days=100), published_at=now)
    await save_rows(engine, old, boundary, recent, unpublished, recently_published_old_row)
    async with AsyncSession(engine) as session:
        async with session.begin():
            assert await cleanup_published_outbox(session, retention_days, now) == 1
    async with AsyncSession(engine) as session:
        remaining = set((await session.scalars(select(Outbox.id))).all())
    assert remaining == {boundary.id, recent.id, unpublished.id, recently_published_old_row.id}
    async with AsyncSession(engine) as session:
        async with session.begin():
            assert await cleanup_published_outbox(session, retention_days, now) == 0


async def test_cleanup_transaction_rollback_preserves_rows(infrastructure):
    from datetime import datetime, timedelta, timezone
    from app.notify.workers.cleanup import cleanup_published_outbox
    engine, redis = infrastructure
    now = datetime.now(timezone.utc)
    row = make_row(published_at=now - timedelta(days=8))
    await save_rows(engine, row)
    async with AsyncSession(engine) as session:
        with pytest.raises(RuntimeError, match='rollback'):
            async with session.begin():
                assert await cleanup_published_outbox(session, 7, now) == 1
                raise RuntimeError('Force rollback')
    async with AsyncSession(engine) as session:
        assert await session.get(Outbox, row.id) is not None

async def test_processed_event_retention_boundaries_and_database_default(infrastructure):
    from datetime import datetime, timedelta, timezone
    from app.notify.workers.cleanup import cleanup_processed_events
    engine, redis = infrastructure
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=14)
    old = ProcessedEvent(event_id=uuid4(), consumer='notify', processed_at=cutoff - timedelta(microseconds=1))
    boundary = ProcessedEvent(event_id=uuid4(), consumer='notify', processed_at=cutoff)
    recent = ProcessedEvent(event_id=uuid4(), consumer='notify', processed_at=cutoff + timedelta(microseconds=1))
    defaulted = ProcessedEvent(event_id=uuid4(), consumer='notify')
    await save_rows(engine, old, boundary, recent, defaulted)
    assert defaulted.processed_at.tzinfo is not None
    assert defaulted.processed_at >= now
    async with AsyncSession(engine) as session:
        async with session.begin():
            assert await cleanup_processed_events(session, now) == 1
    async with AsyncSession(engine) as session:
        remaining = set((await session.scalars(select(ProcessedEvent.event_id))).all())
    assert remaining == {boundary.event_id, recent.event_id, defaulted.event_id}
    async with AsyncSession(engine) as session:
        async with session.begin():
            assert await cleanup_processed_events(session, now) == 0


async def test_both_retention_deletes_rollback_together(infrastructure):
    from datetime import datetime, timedelta, timezone
    from app.notify.workers.cleanup import cleanup_processed_events, cleanup_published_outbox
    engine, redis = infrastructure
    now = datetime.now(timezone.utc)
    outbox = make_row(published_at=now - timedelta(days=8))
    processed = ProcessedEvent(event_id=uuid4(), consumer='notify', processed_at=now - timedelta(days=15))
    await save_rows(engine, outbox, processed)
    async with AsyncSession(engine) as session:
        with pytest.raises(RuntimeError):
            async with session.begin():
                assert await cleanup_published_outbox(session, 7, now) == 1
                assert await cleanup_processed_events(session, now) == 1
                raise RuntimeError('Simulated cleanup failure before commit')
    async with AsyncSession(engine) as session:
        assert await session.get(Outbox, outbox.id) is not None
        assert await session.get(ProcessedEvent, {'event_id': processed.event_id, 'consumer': 'notify'}) is not None


async def test_processed_timestamp_migration_preserves_legacy_rows(infrastructure):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from app.notify.workers.cleanup import cleanup_processed_events
    engine, redis = infrastructure
    migration_path = Path(__file__).resolve().parents[1] / 'alembic/versions/b72c19e4a603_add_processed_event_timestamp.py'
    spec = importlib.util.spec_from_file_location('processed_timestamp_migration', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    event_id = uuid4()

    def exercise_migration(connection):
        schema = connection.get_execution_options()['schema_translate_map'][None]
        quoted_schema = connection.dialect.identifier_preparer.quote(schema)
        connection.execute(text(f'SET LOCAL search_path TO {quoted_schema}'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            connection.execute(
                text('INSERT INTO processed_event (event_id, consumer) VALUES (:id, :consumer)'),
                {'id': event_id, 'consumer': 'notify'},
            )
            migration.upgrade()
            columns = {column['name']: column for column in inspect(connection).get_columns('processed_event', schema=schema)}
            assert columns['processed_at']['nullable'] is False
            assert columns['processed_at']['default'] is not None
            saved = connection.execute(text('SELECT event_id, consumer, processed_at FROM processed_event')).one()
            assert saved.event_id == event_id
            assert saved.consumer == 'notify'
            assert saved.processed_at.tzinfo is not None
            # Check downgrade without dropping or recreating the legacy row.
            migration.downgrade()
            assert connection.scalar(text('SELECT count(*) FROM processed_event')) == 1
            assert 'processed_at' not in {column['name'] for column in inspect(connection).get_columns('processed_event', schema=schema)}
            migration.upgrade()

    async with engine.begin() as connection:
        await connection.run_sync(exercise_migration)
    async with AsyncSession(engine) as session:
        async with session.begin():
            assert await cleanup_processed_events(session) == 0
