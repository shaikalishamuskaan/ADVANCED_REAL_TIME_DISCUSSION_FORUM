import json
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.redis import get_redis_client, close_redis_client
from app.workers import index_consumer as worker
from tests.test_database_integration import database
from tests.test_index_events import documents, ledger, thread_created, event

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get('RUN_SEARCH_INTEGRATION') != '1', reason='Set RUN_SEARCH_INTEGRATION=1; requires local PostgreSQL and Redis')]


@pytest_asyncio.fixture
async def stream_consumer(database, monkeypatch):
    engine, schema = database
    redis = get_redis_client()
    prefix = f'test:search:{uuid4().hex}'
    discussion, identity, dead = f'{prefix}:discussion', f'{prefix}:identity', f'{prefix}:dead'
    mapping = {discussion: 'stream:discussion', identity: 'stream:identity'}
    original_processor = worker.process_event
    async def process_mapped(session, envelope, stream):
        await original_processor(session, envelope, mapping[stream])
    monkeypatch.setattr(worker, 'STREAMS', (discussion, identity))
    monkeypatch.setattr(worker, 'DEAD_STREAM', dead)
    monkeypatch.setattr(worker, 'BLOCK_MS', 10)
    monkeypatch.setattr(worker, 'CLAIM_IDLE_MS', 0)
    monkeypatch.setattr(worker, 'process_event', process_mapped)
    consumer = worker.SearchConsumer(redis, async_sessionmaker(engine, expire_on_commit=False))
    try:
        assert await redis.ping()
        await consumer.ensure_groups()
        yield consumer, redis, engine, discussion, identity, dead
    finally:
        # These randomly named test streams never contain application events.
        await redis.delete(discussion, identity, dead)
        await close_redis_client()


async def test_both_real_streams_commit_and_ack_with_duplicate_delivery(stream_consumer):
    consumer, redis, engine, discussion, identity, dead = stream_consumer
    created = thread_created()
    for _ in range(2):
        await redis.xadd(discussion, {'envelope': json.dumps(created)})
    await consumer.run_once()
    assert len(await documents(engine)) == 1
    assert len(await ledger(engine)) == 1
    assert (await redis.xpending(discussion, worker.GROUP))['pending'] == 0
    rename = event('user.username_changed', {'user_id': created['payload']['author_id'], 'old_username': 'alice', 'new_username': 'renamed'})
    await redis.xadd(identity, {'envelope': json.dumps(rename)})
    await consumer.run_once()
    assert next(iter((await documents(engine)).values())).author_username == 'renamed'
    assert len(await ledger(engine)) == 2
    assert (await redis.xpending(identity, worker.GROUP))['pending'] == 0


async def test_real_pending_recovery_dead_letters_after_five_deliveries(stream_consumer):
    consumer, redis, engine, discussion, identity, dead = stream_consumer
    message_id = await redis.xadd(discussion, {'envelope': 'invalid JSON'})
    for _ in range(5):
        await consumer.run_once()
    assert (await redis.xpending(discussion, worker.GROUP))['pending'] == 0
    dead_rows = await redis.xrange(dead)
    assert len(dead_rows) == 1
    fields = dead_rows[0][1]
    assert fields['source_message_id'] == message_id
    assert fields['source_stream'] == discussion
    assert fields['attempts'] == '5'
    assert not await ledger(engine)
    assert not await documents(engine)
