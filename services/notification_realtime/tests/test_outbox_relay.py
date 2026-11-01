from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app.models.outbox import Outbox
from app.notify.workers import outbox_relay as relay


def make_row(**overrides):
    values = dict(
        id=uuid4(), event_type='notification.created',
        created_at=datetime.now(timezone.utc),
        payload={'target': f'ws:user:{uuid4()}', 'event': {'type': 'notification', 'data': {'id': str(uuid4()), 'type': 'mention'}}},
    )
    values.update(overrides)
    return Outbox(**values)


def make_session(rows):
    session = AsyncMock()
    session.begin = MagicMock(return_value=AsyncMock())
    result = MagicMock()
    result.all.return_value = rows
    session.scalars.return_value = result
    return session


@pytest.mark.asyncio
async def test_publish_preserves_existing_private_payload_without_stream_write():
    import json
    redis = AsyncMock()
    redis.publish.return_value = 0
    row = make_row()
    await relay.publish_row(redis, row)
    channel, data = redis.publish.call_args.args
    assert channel == row.payload['target']
    assert json.loads(data) == row.payload['event']
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('event_type', 'unknown'),
    ('payload', {'target': 'ws:global', 'event': {}}),
    ('payload', {'target': 'ws:user:not-a-uuid', 'event': {}}),
    ('payload', {'target': f'ws:user:{uuid4()}', 'event': {'type': 'event', 'data': {}}}),
    ('payload', {}),
])
async def test_invalid_outbox_row_is_not_published(field, value):
    redis = AsyncMock()
    with pytest.raises((ValueError, KeyError)):
        await relay.publish_row(redis, make_row(**{field: value}))
    redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_query_is_ordered_bounded_and_only_selects_unpublished():
    session = make_session([])
    assert await relay.publish_pending_batch(session, AsyncMock(), 7) == 0
    statement = session.scalars.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'outbox.published_at IS NULL' in sql
    assert 'ORDER BY outbox.created_at, outbox.id' in sql
    assert 'LIMIT 7' in sql
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_each_publish_precedes_its_database_update():
    rows = [make_row(), make_row()]
    session = make_session(rows)
    redis = AsyncMock()
    order = []
    async def publish(channel, data): order.append(('publish', channel))
    async def update(statement): order.append(('update', statement.compile().params['id_1']))
    redis.publish.side_effect = publish
    session.execute.side_effect = update
    assert await relay.publish_pending_batch(session, redis, 100) == 2
    assert order == [('publish', rows[0].payload['target']), ('update', rows[0].id), ('publish', rows[1].payload['target']), ('update', rows[1].id)]


@pytest.mark.asyncio
@pytest.mark.parametrize('failure_index', [0, 1])
async def test_redis_failure_stops_batch_without_marking_failed_or_later_rows(failure_index):
    rows = [make_row() for _ in range(3)]
    session = make_session(rows)
    redis = AsyncMock()
    redis.publish.side_effect = [1] * failure_index + [ConnectionError('Redis down')]
    with pytest.raises(ConnectionError):
        await relay.publish_pending_batch(session, redis, 100)
    assert redis.publish.await_count == failure_index + 1
    assert session.execute.await_count == failure_index


@pytest.mark.asyncio
async def test_database_failure_after_publish_replays_same_payload():
    row = make_row()
    session = make_session([row])
    redis = AsyncMock()
    session.execute.side_effect = SQLAlchemyError('commit failed')
    with pytest.raises(SQLAlchemyError):
        await relay.publish_pending_batch(session, redis, 100)
    first = redis.publish.call_args
    session.execute.side_effect = None
    assert await relay.publish_pending_batch(session, redis, 100) == 1
    assert redis.publish.call_args == first


@pytest.mark.asyncio
@pytest.mark.parametrize('age,alert', [(61, True), (10, False)])
async def test_backlog_alert_after_sixty_seconds(caplog, age, alert):
    row = make_row(created_at=datetime.now(timezone.utc) - timedelta(seconds=age))
    await relay.publish_pending_batch(make_session([row]), AsyncMock(), 100)
    assert ('oldest unpublished row' in caplog.text) is alert
