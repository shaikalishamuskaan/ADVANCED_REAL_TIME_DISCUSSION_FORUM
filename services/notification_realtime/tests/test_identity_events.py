import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError, ResponseError
from starlette.websockets import WebSocketState

from app.notify.workers import consumer as shared
from app.realtime.connection_manager import ConnectionManager
from app.realtime.workers import identity_consumer as worker


@pytest.fixture
def envelope():
    return {
        'event_id': str(uuid4()), 'type': 'user.disabled', 'version': 1,
        'producer': 'identity', 'occurred_at': '2026-11-01T00:00:00Z',
        'payload': {'user_id': str(uuid4())},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('event_type', ['user.disabled', 'user.role_changed', 'user.enabled'])
async def test_status_events_invalidate_only_target_cache(envelope, event_type):
    redis = AsyncMock()
    envelope['type'] = event_type
    await worker.process_identity_event(redis, envelope)
    redis.delete.assert_awaited_once_with(f"rt:user_status:{envelope['payload']['user_id']}")
    if event_type == 'user.disabled':
        redis.publish.assert_awaited_once_with(
            f"ws:user:{envelope['payload']['user_id']}", json.dumps(envelope),
        )
    else:
        redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_ack_after_invalidation_and_fanout(envelope):
    redis = AsyncMock()
    order = []
    async def deleted(*args): order.append('delete')
    async def published(*args): order.append('publish')
    async def acked(*args): order.append('ack')
    redis.delete.side_effect = deleted
    redis.publish.side_effect = published
    redis.xack.side_effect = acked
    await worker.handle_entry(redis, '1-0', {'envelope': json.dumps(envelope)})
    assert order == ['delete', 'publish', 'ack']
    redis.xack.assert_awaited_once_with('stream:identity', 'realtime-cache', '1-0')


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['delete', 'publish'])
async def test_dependency_failure_remains_pending(envelope, operation):
    redis = AsyncMock()
    redis.xpending_range.return_value = [{'times_delivered': 1}]
    getattr(redis, operation).side_effect = ConnectionError('unavailable')
    await worker.handle_entry(redis, '1-0', {'envelope': json.dumps(envelope)})
    redis.xack.assert_not_awaited()
    redis.xadd.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('fields', [{}, {'envelope': 'not json'}, {'envelope': '[]'}, {'envelope': '{}'}])
async def test_invalid_entry_retries_then_dead_letters(fields):
    redis = AsyncMock()
    redis.xpending_range.return_value = [{'times_delivered': 4}]
    await worker.handle_entry(redis, '1-0', fields)
    redis.xack.assert_not_awaited()
    redis.xadd.assert_not_awaited()
    redis.xpending_range.return_value = [{'times_delivered': 5}]
    await worker.handle_entry(redis, '1-0', fields)
    redis.xadd.assert_awaited_once()
    assert redis.xadd.call_args.args[0] == 'stream:dead'
    assert redis.xadd.call_args.args[1]['source_stream'] == 'stream:identity'
    redis.xack.assert_awaited_once_with('stream:identity', 'realtime-cache', '1-0')


@pytest.mark.asyncio
async def test_unknown_identity_event_acknowledged(envelope):
    redis = AsyncMock()
    envelope['type'] = 'user.username_changed'
    await worker.handle_entry(redis, '1-0', {'envelope': json.dumps(envelope)})
    redis.delete.assert_not_awaited()
    redis.publish.assert_not_awaited()
    redis.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_byte_fields_and_duplicate_delivery(envelope):
    redis = AsyncMock()
    fields = {b'envelope': json.dumps(envelope).encode()}
    await worker.handle_entry(redis, '1-0', fields)
    await worker.handle_entry(redis, '1-0', fields)
    assert redis.delete.await_count == redis.publish.await_count == redis.xack.await_count == 2


@pytest.mark.asyncio
async def test_group_creation_and_existing_group():
    redis = AsyncMock()
    await shared.ensure_consumer_group(redis, worker.STREAM_NAME, worker.GROUP_NAME)
    redis.xgroup_create.assert_awaited_once_with(
        name='stream:identity', groupname='realtime-cache', id='0', mkstream=True,
    )
    redis.xgroup_create.side_effect = ResponseError('BUSYGROUP Consumer Group name already exists')
    await shared.ensure_consumer_group(redis, worker.STREAM_NAME, worker.GROUP_NAME)
    redis.xgroup_create.side_effect = ResponseError('Other error')
    with pytest.raises(ResponseError):
        await shared.ensure_consumer_group(redis, worker.STREAM_NAME, worker.GROUP_NAME)


@pytest.mark.asyncio
async def test_disabled_user_all_sockets_cleaned_without_affecting_other_user():
    manager = ConnectionManager()
    user, other = uuid4(), uuid4()
    sockets = [AsyncMock() for _ in range(3)]
    for index, ws in enumerate(sockets):
        ws.application_state = WebSocketState.CONNECTED
        await manager.connect(ws, user if index < 2 else other)
        await manager.subscribe_thread(ws, uuid4())
    closed = [manager.socket_closed[ws] for ws in sockets]
    sockets[0].close.side_effect = OSError('already disconnected')
    await manager.disconnect_user(user)
    for ws in sockets[:2]:
        ws.close.assert_awaited_once_with(code=4403, reason='account_disabled')
        assert ws not in manager.socket_users
        assert all(ws not in room for room in manager.rooms.values())
    assert closed[0].is_set() and closed[1].is_set()
    assert not closed[2].is_set()
    assert await manager.connection_count(other) == 1
    sockets[2].close.assert_not_awaited()
    await manager.disconnect_user(user)
    await manager.disconnect(sockets[2])


@pytest.mark.asyncio
async def test_pending_recovery_and_new_messages(monkeypatch, envelope):
    redis = AsyncMock()
    redis.xautoclaim.return_value = ['0-0', [('1-0', {'envelope': json.dumps(envelope)})], []]
    redis.xreadgroup.return_value = [('stream:identity', [('2-0', {'envelope': json.dumps(envelope)})])]
    handled = []
    async def handle(client, message_id, fields):
        handled.append(message_id)
        if len(handled) == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(worker, 'get_redis_client', lambda: redis)
    monkeypatch.setattr(worker, 'handle_entry', handle)
    with pytest.raises(asyncio.CancelledError):
        await worker.consume_identity_forever()
    assert handled == ['1-0', '2-0']
    assert redis.xreadgroup.call_args.kwargs['streams'] == {'stream:identity': '>'}
    assert redis.xautoclaim.call_args.kwargs['groupname'] == 'realtime-cache'

@pytest.mark.asyncio
@pytest.mark.parametrize('channel,payload,expected', [
    ('matching', 'disabled', 'close'),
    ('wrong', 'disabled', 'ignore'),
    ('matching', '[]', 'ignore'),
    ('matching', 'invalid JSON', 'ignore'),
    ('matching', '{"type":"notification","data":{}}', 'forward'),
])
async def test_listener_control_events_are_internal(monkeypatch, envelope, channel, payload, expected):
    from unittest.mock import Mock
    from app.realtime.workers import pubsub_listener
    user_id = envelope['payload']['user_id']
    actual_channel = f'ws:user:{user_id}' if channel == 'matching' else f'ws:user:{uuid4()}'
    raw = json.dumps(envelope) if payload == 'disabled' else payload
    pubsub = AsyncMock()
    pubsub.get_message.side_effect = [
        {'channel': actual_channel, 'data': raw}, asyncio.CancelledError,
    ]
    redis = Mock()
    redis.pubsub.return_value = pubsub
    manager = AsyncMock()
    monkeypatch.setattr(pubsub_listener, 'get_redis_client', lambda: redis)
    monkeypatch.setattr(pubsub_listener, 'manager', manager)
    with pytest.raises(asyncio.CancelledError):
        await pubsub_listener.listen_to_redis()
    if expected == 'close':
        from uuid import UUID
        manager.disconnect_user.assert_awaited_once_with(UUID(user_id))
    else:
        manager.disconnect_user.assert_not_awaited()
    if expected == 'forward':
        manager.publish_to_room.assert_awaited_once()
    else:
        manager.publish_to_room.assert_not_awaited()
    pubsub.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_all_workers(monkeypatch):
    from app import main
    redis = AsyncMock()
    close_redis = AsyncMock()
    started, stopped = set(), set()

    def make_worker(name):
        async def run():
            started.add(name)
            try:
                await asyncio.Event().wait()
            finally:
                stopped.add(name)
        return run

    monkeypatch.setattr(main, 'get_redis_client', lambda: redis)
    monkeypatch.setattr(main, 'close_redis_client', close_redis)
    for name in ['consume_forever', 'listen_to_redis', 'consume_identity_forever', 'run_outbox_relay', 'run_cleanup_forever']:
        monkeypatch.setattr(main, name, make_worker(name))
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert len(started) == 5
        redis.ping.assert_awaited_once()
    assert stopped == started
    close_redis.assert_awaited_once()
