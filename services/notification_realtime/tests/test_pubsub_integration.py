import asyncio
import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketState

from app.core.redis import close_redis_client, get_redis_client
from app.realtime.connection_manager import ConnectionManager
from app.realtime.workers import pubsub_listener


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get('RUN_REDIS_INTEGRATION') != '1',
    reason='Opt-in Redis integration test: set RUN_REDIS_INTEGRATION=1 (requires local Redis)',
)
async def test_two_independent_listeners_receive_same_publication():
    redis = get_redis_client()
    thread_id = uuid4()
    tasks = []
    sockets = []
    try:
        assert await redis.ping()
        for index in range(2):
            spec = importlib.util.spec_from_file_location(f'listener_{index}', Path(pubsub_listener.__file__))
            listener = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(listener)
            listener.manager = ConnectionManager()
            socket = AsyncMock()
            socket.application_state = WebSocketState.CONNECTED
            await listener.manager.connect(socket, uuid4())
            await listener.manager.subscribe_thread(socket, thread_id)
            sockets.append(socket)
            tasks.append(asyncio.create_task(listener.listen_to_redis()))
        async with asyncio.timeout(5):
            while not all(socket.send_text.await_count for socket in sockets):
                await redis.publish(f'ws:thread:{thread_id}', '{"type":"event","event":"comment.created","data":{}}')
                await asyncio.sleep(0.02)
        for socket in sockets:
            assert 'comment.created' in socket.send_text.call_args.args[0]
        assert all(not task.done() for task in tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_redis_client()

@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('RUN_REDIS_INTEGRATION') != '1', reason='Opt-in Redis integration test: set RUN_REDIS_INTEGRATION=1')
async def test_identity_disable_stream_closes_sockets_on_two_instances(monkeypatch):
    import json
    from types import SimpleNamespace
    from app.realtime.workers import identity_consumer

    redis = get_redis_client()
    user_id = uuid4()
    stream = f'test:realtime-identity:{uuid4()}'
    cache_key = f'rt:user_status:{user_id}'
    tasks, sockets = [], []
    monkeypatch.setattr(identity_consumer, 'STREAM_NAME', stream)
    try:
        await redis.set(cache_key, json.dumps({'status': 'active', 'role': 'member'}), ex=30)
        await identity_consumer.ensure_consumer_group(redis, stream, identity_consumer.GROUP_NAME)
        for index in range(2):
            spec = importlib.util.spec_from_file_location(f'disable_listener_{index}', Path(pubsub_listener.__file__))
            listener = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(listener)
            listener.manager = ConnectionManager()
            # Confirm the actual Redis subscription before publishing a single event.
            pubsub = redis.pubsub()
            await pubsub.psubscribe('ws:*')
            async with asyncio.timeout(3):
                while True:
                    ack = await pubsub.get_message(timeout=0.1)
                    if ack and ack['type'] == 'psubscribe':
                        break
            listener.get_redis_client = lambda subscription=pubsub: SimpleNamespace(pubsub=lambda: subscription)
            ws = AsyncMock()
            ws.application_state = WebSocketState.CONNECTED
            await listener.manager.connect(ws, user_id)
            await listener.manager.subscribe_thread(ws, uuid4())
            sockets.append((ws, listener.manager))
            tasks.append(asyncio.create_task(listener.listen_to_redis()))
        tasks.append(asyncio.create_task(identity_consumer.consume_identity_forever()))
        envelope = {
            'event_id': str(uuid4()), 'type': 'user.disabled', 'version': 1,
            'producer': 'identity', 'occurred_at': '2026-11-01T00:00:00Z',
            'payload': {'user_id': str(user_id)},
        }
        await redis.xadd(stream, {'envelope': json.dumps(envelope)})
        async with asyncio.timeout(5):
            while True:
                pending = await redis.xpending(stream, identity_consumer.GROUP_NAME)
                if all(ws.close.await_count and not manager.socket_users for ws, manager in sockets) and pending['pending'] == 0:
                    break
                await asyncio.sleep(0.01)
        assert await redis.get(cache_key) is None
        for ws, manager in sockets:
            ws.close.assert_awaited_once_with(code=4403, reason='account_disabled')
            ws.send_text.assert_not_awaited()
            assert not manager.rooms
        assert all(not task.done() for task in tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Only remove this test's randomly named stream and user cache key.
        await redis.delete(stream, cache_key)
        await close_redis_client()
