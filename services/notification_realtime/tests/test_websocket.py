import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import auth
from app.api.routers import realtime as rt
from app.realtime.connection_manager import ConnectionManager

USER = uuid4()
THREAD = uuid4()


class HeartbeatClock:
    """Advance heartbeat deadlines on the server loop without real-time races."""

    def __init__(self):
        self.now = 0.0
        self.waits = asyncio.Queue()

    async def sleep(self, delay):
        wake = asyncio.get_running_loop().create_future()
        self.waits.put_nowait((self.now + delay, wake))
        await wake

    async def tick(self, delayed_by=0):
        # This timeout only guards a broken test; it does not drive the heartbeat.
        async with asyncio.timeout(2):
            deadline, wake = await self.waits.get()
        self.now = deadline + delayed_by
        wake.set_result(None)
        await asyncio.sleep(0)


@pytest.fixture
def heartbeat_clock(monkeypatch):
    clock = HeartbeatClock()
    monkeypatch.setattr(rt, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(rt, 'sleep', clock.sleep)
    return clock


@pytest.fixture
def setup(monkeypatch):
    manager = ConnectionManager()
    monkeypatch.setattr(rt, 'manager', manager)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, 'get_public_key', lambda: private.public_key())
    redis = AsyncMock()
    redis.get.return_value = None
    monkeypatch.setattr(rt, 'get_redis_client', lambda: redis)
    identity = AsyncMock(return_value={'status': 'active', 'role': 'member'})
    monkeypatch.setattr(rt, 'fetch_user_status', identity)
    app = FastAPI()
    app.include_router(rt.router)
    settings = auth.get_settings()

    def token(**overrides):
        import time
        claims = dict(sub=str(USER), exp=int(time.time()) + 60, iss=settings.JWT_ISSUER, aud=settings.JWT_AUDIENCE)
        claims.update(overrides)
        return jwt.encode(claims, private, algorithm='RS256')

    with TestClient(app) as client:
        yield client, token, manager, redis, identity


def login(ws, token):
    ws.send_json({'type': 'auth', 'token': token()})
    assert ws.receive_json() == {'type': 'auth.ok', 'user_id': str(USER), 'role': 'member'}


@pytest.mark.parametrize('message', [{}, {'type': 'ping'}, {'type': 'auth', 'token': 'bad'}, {'type': 'auth', 'token': ''}])
def test_invalid_auth(setup, message):
    client, *_ = setup
    with client.websocket_connect('/ws') as ws:
        ws.send_json(message)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_auth_timeout(setup, monkeypatch):
    monkeypatch.setattr(rt, 'AUTH_TIMEOUT', 0.01)
    with setup[0].websocket_connect('/ws') as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


@pytest.mark.parametrize('claims', [{'exp': 1}, {'iss': 'wrong'}, {'aud': 'wrong'}, {'sub': 'invalid'}])
def test_invalid_claims(setup, claims):
    client, token, *_ = setup
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token(**claims)})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_disabled(setup):
    client, token, _, _, identity = setup
    identity.return_value = {'status': 'disabled', 'role': 'member'}
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4403


def test_success_cache_and_ping(setup):
    client, token, manager, redis, identity = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        redis.set.assert_awaited_once()
        assert redis.set.call_args.args[0] == f'rt:user_status:{USER}'
        assert redis.set.call_args.kwargs['ex'] == 30
        assert len(manager.socket_users) == 1
    assert not manager.rooms
    assert not manager.socket_users
    assert not manager.user_connections


def test_cached_status(setup):
    client, token, _, redis, identity = setup
    redis.get.return_value = json.dumps({'status': 'active', 'role': 'admin'})
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        assert ws.receive_json()['role'] == 'admin'
    identity.assert_not_awaited()


def test_url_token_rejected(setup):
    with setup[0].websocket_connect('/ws?token=secret') as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_connection_limit(setup):
    from contextlib import ExitStack
    client, token, manager, *_ = setup
    with ExitStack() as stack:
        for _ in range(5):
            ws = stack.enter_context(client.websocket_connect('/ws'))
            login(ws, token)
        with client.websocket_connect('/ws') as ws:
            ws.send_json({'type': 'auth', 'token': token()})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4429
    assert not manager.rooms


def test_rate_limit(setup):
    client, token, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        for _ in range(20):
            ws.send_json({'type': 'ping'})
            assert ws.receive_json() == {'type': 'pong'}
        ws.send_json({'type': 'ping'})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4429


def test_subscribe_unsubscribe_and_delivery(setup):
    client, token, manager, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        ws.send_json({'type': 'subscribe', 'thread_id': str(THREAD)})
        # Ping is a barrier: subscription intentionally has no acknowledgement.
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        for channel in ['ws:global', f'ws:user:{USER}', f'ws:thread:{THREAD}']:
            client.portal.call(manager.publish_to_room, channel, {'type': 'event', 'data': channel})
            assert ws.receive_json()['data'] == channel
        client.portal.call(manager.publish_to_room, f'ws:user:{uuid4()}', {'type': 'wrong'})
        client.portal.call(manager.publish_to_room, f'ws:thread:{uuid4()}', {'type': 'wrong'})
        ws.send_json({'type': 'unsubscribe', 'thread_id': str(THREAD)})
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        client.portal.call(manager.publish_to_room, f'ws:thread:{THREAD}', {'type': 'wrong'})
        ws.send_json({'type': 'unsubscribe', 'thread_id': str(THREAD)})
        assert ws.receive_json() == {'type': 'error', 'code': 'not_subscribed'}
    assert not manager.rooms


def test_heartbeat_timeout(setup, heartbeat_clock):
    client, token, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        client.portal.call(heartbeat_clock.tick)
        assert heartbeat_clock.now == 30
        assert ws.receive_json() == {'type': 'ping'}
        # Client pings receive a pong but do not answer the server heartbeat.
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        client.portal.call(heartbeat_clock.tick)
        assert heartbeat_clock.now == 60
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1001
        assert exc.value.reason == 'heartbeat_timeout'


def test_heartbeat_pong(setup, heartbeat_clock):
    client, token, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        for _ in range(8):
            client.portal.call(heartbeat_clock.tick)
            assert ws.receive_json() == {'type': 'ping'}
            ws.send_json({'type': 'pong'})
            # Ensure the server processed the pong before advancing time again.
            ws.send_json({'type': 'ping'})
            assert ws.receive_json() == {'type': 'pong'}
        assert heartbeat_clock.now == 240


def test_heartbeat_delayed_wakeup_closes_without_sending_stale_ping(setup, heartbeat_clock):
    client, token, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        # Reproduce a scheduler delay that skips the initial ping deadline.
        client.portal.call(heartbeat_clock.tick, 60)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1001
        assert exc.value.reason == 'heartbeat_timeout'


def test_heartbeat_pong_deadline_between_ping_intervals(setup, heartbeat_clock):
    client, token, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        client.portal.call(heartbeat_clock.tick)
        assert ws.receive_json() == {'type': 'ping'}
        client.portal.call(setattr, heartbeat_clock, 'now', 40)
        ws.send_json({'type': 'pong'})
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        for expected_time in (60, 90):
            client.portal.call(heartbeat_clock.tick)
            assert heartbeat_clock.now == expected_time
            assert ws.receive_json() == {'type': 'ping'}
        client.portal.call(heartbeat_clock.tick)
        assert heartbeat_clock.now == 100
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1001


@pytest.mark.parametrize('payload', ['not json', '[]', '{"type":"subscribe","thread_id":"invalid"}'])
def test_malformed_authenticated_message(setup, payload):
    client, token, manager, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        ws.send_text(payload)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008
    assert not manager.rooms


def test_binary_auth_rejected(setup):
    with setup[0].websocket_connect('/ws') as ws:
        ws.send_bytes(b'auth')
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_identity_unavailable(setup):
    import httpx
    client, token, manager, _, identity = setup
    identity.side_effect = httpx.ConnectError('Unavailable')
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1011
    assert not manager.rooms

@pytest.mark.parametrize('claim', ['exp', 'sub', 'iss', 'aud'])
def test_required_jwt_claims(setup, monkeypatch, claim):
    client, token, manager, _, identity = setup
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, 'get_public_key', lambda: private.public_key())
    claims = jwt.decode(token(), options={'verify_signature': False})
    claims.pop(claim)
    encoded = jwt.encode(claims, private, algorithm='RS256')
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': encoded})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    identity.assert_not_awaited()
    assert not manager.rooms


@pytest.mark.parametrize('algorithm', ['RS256', 'HS256', 'none'])
def test_wrong_signature_or_algorithm(setup, algorithm):
    client, token, manager, _, identity = setup
    claims = jwt.decode(token(), options={'verify_signature': False})
    if algorithm == 'RS256':
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    else:
        key = 'test-only-hmac-secret-at-least-32-bytes' if algorithm == 'HS256' else None
    encoded = jwt.encode(claims, key, algorithm=algorithm)
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': encoded})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    identity.assert_not_awaited()
    assert not manager.rooms


def test_corrupt_status_cache_refetched(setup):
    client, token, _, redis, identity = setup
    redis.get.return_value = 'invalid JSON'
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
    identity.assert_awaited_once_with(str(USER))
    redis.set.assert_awaited_once()


def test_cached_disabled_account(setup):
    client, token, manager, redis, identity = setup
    redis.get.return_value = json.dumps({'status': 'disabled', 'role': 'member'})
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4403
    identity.assert_not_awaited()
    assert not manager.rooms


@pytest.mark.parametrize('operation', ['get', 'set'])
def test_redis_failure_closes_without_registration(setup, operation):
    from redis.exceptions import ConnectionError
    client, token, manager, redis, _ = setup
    getattr(redis, operation).side_effect = ConnectionError('Unavailable')
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1011
    assert not manager.rooms
    assert not manager.socket_users


@pytest.mark.parametrize('status_code,close_code', [(404, 4401), (500, 1011), (403, 1011)])
def test_identity_http_errors(setup, status_code, close_code):
    import httpx
    client, token, manager, _, identity = setup
    request = httpx.Request('GET', f'http://identity/internal/users/{USER}/status')
    response = httpx.Response(status_code, request=request)
    identity.side_effect = httpx.HTTPStatusError('Failure', request=request, response=response)
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == close_code
    assert not manager.rooms


@pytest.mark.parametrize('data', [{}, {'status': 'unknown', 'role': 'member'}, {'status': 'active', 'role': 'invalid'}])
def test_invalid_identity_status(setup, data):
    client, token, manager, _, identity = setup
    identity.return_value = data
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1011
    assert not manager.rooms


def test_invalid_identity_json(setup):
    client, token, manager, _, identity = setup
    identity.side_effect = ValueError('Invalid JSON')
    with client.websocket_connect('/ws') as ws:
        ws.send_json({'type': 'auth', 'token': token()})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1011
    assert not manager.rooms


def test_rate_limit_resets_after_minute(setup, monkeypatch):
    client, token, _, _, _ = setup
    clock = [100.0]
    monkeypatch.setattr(rt, 'monotonic', lambda: clock[0])
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        for _ in range(20):
            ws.send_json({'type': 'ping'})
            assert ws.receive_json() == {'type': 'pong'}
        clock[0] += 60
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}


def test_rate_limits_are_per_socket(setup):
    client, token, _, _, _ = setup
    with client.websocket_connect('/ws') as first, client.websocket_connect('/ws') as second:
        login(first, token)
        login(second, token)
        for _ in range(20):
            first.send_json({'type': 'ping'})
            assert first.receive_json() == {'type': 'pong'}
        first.send_json({'type': 'ping'})
        with pytest.raises(WebSocketDisconnect) as exc:
            first.receive_json()
        assert exc.value.code == 4429
        second.send_json({'type': 'ping'})
        assert second.receive_json() == {'type': 'pong'}


def test_heartbeat_cleans_up_without_client_disconnect(setup, heartbeat_clock):
    client, token, manager, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        ws.send_json({'type': 'subscribe', 'thread_id': str(THREAD)})
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        client.portal.call(heartbeat_clock.tick)
        assert ws.receive_json() == {'type': 'ping'}
        client.portal.call(heartbeat_clock.tick)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1001

        async def wait_for_cleanup():
            async with asyncio.timeout(1):
                while manager.socket_users:
                    await asyncio.sleep(0.001)
        client.portal.call(wait_for_cleanup)
        assert not manager.rooms
        assert not manager.user_connections


@pytest.mark.parametrize('message', [
    {'type': 'subscribe'}, {'type': 'unsubscribe'},
    {'type': 'ping', 'thread_id': str(THREAD)},
    {'type': 'pong', 'thread_id': str(THREAD)},
    {'type': 'auth', 'token': 'repeat'},
])
def test_invalid_session_protocol(setup, message):
    client, token, manager, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        ws.send_json(message)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1008
    assert not manager.rooms

@pytest.mark.asyncio
async def test_identity_status_client_uses_internal_endpoint(monkeypatch):
    import httpx
    from app.clients.identity import fetch_user_status
    settings = auth.get_settings()
    real_client = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'id': str(USER), 'status': 'active', 'role': 'member'})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    data = await fetch_user_status(str(USER))
    assert data['status'] == 'active'
    assert len(requests) == 1
    assert str(requests[0].url) == f'{settings.IDENTITY_BASE_URL}/internal/users/{USER}/status'
    assert requests[0].method == 'GET'
    assert requests[0].headers['X-Service-Key'] == settings.IDENTITY_SERVICE_KEY


def test_disconnect_releases_connection_slot(setup):
    from contextlib import ExitStack
    client, token, manager, *_ = setup
    with ExitStack() as stack:
        for _ in range(4):
            ws = stack.enter_context(client.websocket_connect('/ws'))
            login(ws, token)
        with client.websocket_connect('/ws') as ws:
            login(ws, token)
        with client.websocket_connect('/ws') as replacement:
            login(replacement, token)
            assert len(manager.socket_users) == 5
    assert not manager.rooms


@pytest.mark.asyncio
async def test_delivery_failure_removes_socket_from_all_rooms():
    from starlette.websockets import WebSocketState
    manager = ConnectionManager()
    socket = AsyncMock()
    socket.application_state = WebSocketState.CONNECTED
    await manager.connect(socket, USER)
    await manager.subscribe_thread(socket, THREAD)
    socket.send_text.side_effect = OSError('Connection lost')
    await manager.publish_to_room('ws:global', {'type': 'event', 'data': {}})
    assert not manager.rooms
    assert not manager.socket_users
    assert not manager.user_connections
    # A receive already in flight cannot re-register a disconnected socket.
    await manager.subscribe_thread(socket, THREAD)
    assert not manager.rooms


def test_disable_closes_running_session_and_cleans_up(setup):
    client, token, manager, *_ = setup
    with client.websocket_connect('/ws') as ws:
        login(ws, token)
        ws.send_json({'type': 'subscribe', 'thread_id': str(THREAD)})
        ws.send_json({'type': 'ping'})
        assert ws.receive_json() == {'type': 'pong'}
        client.portal.call(manager.disconnect_user, USER)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4403
        assert not manager.rooms
        assert not manager.socket_users
        assert not manager.socket_closed
