"""Opt-in local infrastructure checks; all writes use a random schema/stream."""
import asyncio
import json
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import get_settings
from app.models.outbox import Outbox
from app.outbox import relay
from tests.test_outbox_relay import row

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DISCUSSION_INTEGRATION") != "1", reason="Set RUN_DISCUSSION_INTEGRATION=1; requires local PostgreSQL and Redis")


async def test_real_outbox_retry_delivers_same_event_to_stream_and_two_live_listeners():
    schema, stream = f"test_discussion_outbox_{uuid4().hex}", f"test:discussion:{uuid4().hex}"
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, execution_options={"schema_translate_map": {None: schema}})
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsubs, created = [], False
    event = row("comment.created")
    channel = f"ws:thread:{event.payload['payload']['thread_id']}"

    class TestDestinations:
        async def xadd(self, destination, fields, **kwargs):
            assert destination == "stream:discussion"
            # Do not send test events into application consumer groups.
            return await redis.xadd(stream, fields, **kwargs)
        async def publish(self, destination, message):
            assert destination == channel
            return await redis.publish(destination, message)

    async def receive(pubsub):
        async with asyncio.timeout(3):
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=.1)
                if message: return json.loads(message["data"])

    try:
        assert await redis.ping()
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            created = True
            await connection.run_sync(Outbox.__table__.create)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin(): session.add(event)
        for _ in range(2):
            pubsub = redis.pubsub()
            pubsubs.append(pubsub)
            await pubsub.subscribe(channel)
            async with asyncio.timeout(3):
                while not await pubsub.get_message(timeout=.1): pass

        failing = TestDestinations()
        failing.publish = AsyncMock(side_effect=ConnectionError("Simulated interruption after stream delivery"))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            with pytest.raises(ConnectionError): await relay.publish_pending_batch(session, failing, 10)
        async with AsyncSession(engine) as session:
            assert (await session.get(Outbox, event.id)).published_at is None
        async with AsyncSession(engine, expire_on_commit=False) as session:
            assert await relay.publish_pending_batch(session, TestDestinations(), 10) == 1
        first, second = await asyncio.gather(*(receive(pubsub) for pubsub in pubsubs))
        assert first == second and first["data"] == event.payload["payload"]
        entries = await redis.xrange(stream)
        assert len(entries) == 2
        assert {json.loads(fields["envelope"])["event_id"] for _, fields in entries} == {str(event.id)}
        async with AsyncSession(engine, expire_on_commit=False) as session:
            assert (await session.get(Outbox, event.id)).published_at is not None
            await session.rollback()
            assert await relay.publish_pending_batch(session, TestDestinations(), 10) == 0
    finally:
        for pubsub in pubsubs: await pubsub.aclose()
        await redis.delete(stream)
        await redis.aclose()
        if created:
            async with engine.begin() as connection: await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()
