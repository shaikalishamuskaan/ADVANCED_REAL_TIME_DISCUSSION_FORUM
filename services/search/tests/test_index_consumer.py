import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ResponseError
from sqlalchemy.exc import SQLAlchemyError

from app.workers import index_consumer as worker


def consumer_with_session():
    redis = AsyncMock()
    session = AsyncMock()
    transaction = AsyncMock()
    session.begin = MagicMock(return_value=transaction)
    context = AsyncMock()
    context.__aenter__.return_value = session
    consumer = worker.SearchConsumer(redis, MagicMock(return_value=context))
    return consumer, redis, session, transaction


@pytest.mark.asyncio
async def test_ack_only_after_database_commit(monkeypatch):
    consumer, redis, session, transaction = consumer_with_session()
    order = []
    async def processed(*args): order.append('processed')
    async def committed(*args): order.append('committed')
    async def acked(*args): order.append('acked')
    monkeypatch.setattr(worker, 'process_event', AsyncMock(side_effect=processed))
    transaction.__aexit__.side_effect = committed
    redis.xack.side_effect = acked
    await consumer.handle_entry(b'stream:discussion', '1-0', {b'envelope': b'{}'})
    assert order == ['processed', 'committed', 'acked']
    redis.xack.assert_awaited_once_with('stream:discussion', 'search', '1-0')


@pytest.mark.asyncio
async def test_commit_failure_remains_pending(monkeypatch):
    consumer, redis, session, transaction = consumer_with_session()
    monkeypatch.setattr(worker, 'process_event', AsyncMock())
    transaction.__aexit__.side_effect = SQLAlchemyError('Commit failed')
    redis.xpending_range.return_value = [{'times_delivered': 1}]
    await consumer.handle_entry('stream:identity', '1-0', {'envelope': '{}'})
    redis.xack.assert_not_awaited()
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('attempts', [1, 4, 5])
async def test_failed_entries_retry_then_dead_letter_before_ack(attempts):
    consumer, redis, session, transaction = consumer_with_session()
    redis.xpending_range.return_value = [{b'times_delivered': attempts}]
    order = []
    async def dead(*args): order.append('dead')
    async def ack(*args): order.append('ack')
    redis.xadd.side_effect = dead
    redis.xack.side_effect = ack
    await consumer.handle_entry('stream:discussion', '1-0', {'envelope': 'invalid json'})
    if attempts < 5:
        assert order == []
    else:
        assert order == ['dead', 'ack']
        fields = redis.xadd.call_args.args[1]
        assert fields['source_stream'] == 'stream:discussion'
        assert fields['attempts'] == '5'


@pytest.mark.asyncio
async def test_dead_letter_failure_does_not_ack():
    consumer, redis, session, transaction = consumer_with_session()
    redis.xpending_range.return_value = [{'times_delivered': 5}]
    redis.xadd.side_effect = ConnectionError('Redis unavailable')
    with pytest.raises(ConnectionError):
        await consumer.handle_entry('stream:discussion', '1-0', {})
    redis.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_groups_created_on_both_streams_and_busygroup_is_allowed():
    consumer, redis, session, transaction = consumer_with_session()
    await consumer.ensure_groups()
    assert [call.kwargs['name'] for call in redis.xgroup_create.call_args_list] == list(worker.STREAMS)
    assert all(call.kwargs['id'] == '0' for call in redis.xgroup_create.call_args_list)
    redis.xgroup_create.side_effect = ResponseError('BUSYGROUP Consumer Group already exists')
    await consumer.ensure_groups()
    redis.xgroup_create.side_effect = ResponseError('Other failure')
    with pytest.raises(ResponseError):
        await consumer.ensure_groups()


@pytest.mark.asyncio
async def test_pending_entries_are_recovered_from_each_stream_before_new_messages():
    consumer, redis, session, transaction = consumer_with_session()
    consumer.handle_entry = AsyncMock()
    redis.xautoclaim.side_effect = [['9-0', [('1-0', {})], []], ['0-0', [('2-0', {})], []]]
    redis.xreadgroup.return_value = [('stream:discussion', [('3-0', {})])]
    await consumer.run_once()
    assert consumer.claim_cursors == {'stream:discussion': '9-0', 'stream:identity': '0-0'}
    assert [call.args[:2] for call in consumer.handle_entry.call_args_list] == [
        ('stream:discussion', '1-0'), ('stream:identity', '2-0'), ('stream:discussion', '3-0'),
    ]
    assert redis.xreadgroup.call_args.kwargs['streams'] == {'stream:discussion': '>', 'stream:identity': '>'}


@pytest.mark.asyncio
async def test_startup_failure_backs_off_and_can_be_cancelled(monkeypatch):
    consumer, redis, session, transaction = consumer_with_session()
    redis.xgroup_create.side_effect = ConnectionError('Unavailable')
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(worker.asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        await consumer.run()
    sleep.assert_awaited_once_with(1)
