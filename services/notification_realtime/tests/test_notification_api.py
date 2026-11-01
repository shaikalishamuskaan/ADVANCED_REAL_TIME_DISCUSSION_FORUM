import base64
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.routers import notifications as api
from app.core.database import get_db
from app.core.errors import install_error_handlers
from app.models.notification import Notification
from tests.test_outbox_integration import infrastructure, save_rows

USER = uuid4()


def notification(**overrides):
    values = dict(
        id=uuid4(), recipient_id=USER, type='mention', actor_id=uuid4(),
        thread_id=uuid4(), comment_id=None, source_event_id=uuid4(),
        read_at=None, created_at=datetime.now(timezone.utc),
    )
    values.update(overrides)
    return Notification(**values)


def make_app():
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: {'id': USER}
    return app


@pytest_asyncio.fixture
async def unit_api(monkeypatch):
    app = make_app()
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    async def database():
        yield session
    app.dependency_overrides[get_db] = database
    profiles = AsyncMock(return_value={})
    monkeypatch.setattr(api, 'get_user_profiles', profiles)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, app, session, profiles


@pytest.mark.asyncio
@pytest.mark.parametrize('path,method', [
    ('/api/notifications', 'get'), ('/api/notifications/unread-count', 'get'),
    ('/api/notifications/read-all', 'post'), (f'/api/notifications/{uuid4()}/read', 'post'),
])
async def test_all_notification_endpoints_require_auth(unit_api, path, method):
    client, app, session, _ = unit_api
    app.dependency_overrides.pop(get_current_user)
    response = await getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'unauthenticated'
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('cursor', [
    'not base64!', '%%%%', base64.urlsafe_b64encode(b'no separator').decode(),
    base64.urlsafe_b64encode(f'2026-11-01T12:00:00|{uuid4()}'.encode()).decode(),
    base64.urlsafe_b64encode(b'2026-11-01T12:00:00+00:00|invalid').decode(),
    base64.urlsafe_b64encode(b'\xff').decode(),
])
async def test_invalid_cursor_returns_lld_error_without_query(unit_api, cursor):
    client, _, session, _ = unit_api
    response = await client.get('/api/notifications', params={'cursor': cursor})
    assert response.status_code == 400
    assert response.json() == {'error': {'code': 'invalid_cursor', 'message': 'Invalid cursor', 'details': {}}}
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [{'limit': 0}, {'limit': 51}, {'limit': 'bad'}, {'unread': 'bad'}])
async def test_invalid_query_returns_400_validation_error(unit_api, query):
    response = await unit_api[0].get('/api/notifications', params=query)
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'validation_error'
    assert 'field' in response.json()['error']['details']


@pytest.mark.asyncio
async def test_invalid_notification_id_returns_400(unit_api):
    response = await unit_api[0].post('/api/notifications/not-a-uuid/read')
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'validation_error'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [httpx.ConnectError('private upstream URL'), ValueError('invalid JSON')])
async def test_identity_failure_becomes_503(unit_api, failure):
    client, _, session, profiles = unit_api
    session.execute.return_value.scalars.return_value.all.return_value = [notification()]
    profiles.side_effect = failure
    response = await client.get('/api/notifications')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'dependency_unavailable'
    assert str(failure) not in response.text


@pytest.mark.asyncio
async def test_missing_actor_profile_returns_503(unit_api):
    client, _, session, _ = unit_api
    session.execute.return_value.scalars.return_value.all.return_value = [notification()]
    response = await client.get('/api/notifications')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'dependency_unavailable'


@pytest.mark.asyncio
async def test_database_failure_returns_safe_503(unit_api):
    client, _, session, _ = unit_api
    session.execute.side_effect = SQLAlchemyError('secret database connection details')
    response = await client.get('/api/notifications')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'dependency_unavailable'
    assert 'secret' not in response.text


@pytest.mark.asyncio
async def test_empty_inbox_response(unit_api):
    response = await unit_api[0].get('/api/notifications')
    assert response.status_code == 200
    assert response.json() == {'items': [], 'next_cursor': None}


@pytest_asyncio.fixture
async def database_api(infrastructure, monkeypatch):
    engine, redis = infrastructure
    app = make_app()
    async def database():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    app.dependency_overrides[get_db] = database
    async def profiles(ids):
        return {user_id: {'id': user_id, 'username': 'actor_name'} for user_id in ids}
    monkeypatch.setattr(api, 'get_user_profiles', profiles)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client, engine


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('RUN_OUTBOX_INTEGRATION') != '1', reason='Set RUN_OUTBOX_INTEGRATION=1; requires local PostgreSQL and Redis')
class TestNotificationApiIntegration:
    async def test_inbox_is_private_and_pagination_handles_tied_timestamps(self, database_api):
        client, engine = database_api
        created = datetime.now(timezone.utc)
        notes = [notification(id=UUID(int=index), created_at=created) for index in range(1, 6)]
        other = notification(recipient_id=uuid4(), created_at=created + timedelta(days=1))
        await save_rows(engine, *notes, other)
        response = await client.get('/api/notifications', params={'limit': 2})
        assert response.status_code == 200
        body = response.json()
        assert [item['id'] for item in body['items']] == [str(notes[4].id), str(notes[3].id)]
        assert body['items'][0]['actor']['username'] == 'actor_name'
        assert body['items'][0]['comment_id'] is None
        received = list(body['items'])
        while body['next_cursor']:
            response = await client.get('/api/notifications', params={'limit': 2, 'cursor': body['next_cursor']})
            assert response.status_code == 200
            body = response.json()
            received.extend(body['items'])
        assert [item['id'] for item in received] == [str(note.id) for note in reversed(notes)]

    async def test_default_page_size_twenty_and_maximum_fifty(self, database_api):
        client, engine = database_api
        await save_rows(engine, *(notification() for _ in range(25)))
        response = await client.get('/api/notifications')
        assert len(response.json()['items']) == 20
        assert response.json()['next_cursor'] is not None
        response = await client.get('/api/notifications', params={'limit': 50})
        assert len(response.json()['items']) == 25
        assert response.json()['next_cursor'] is None

    async def test_unread_filter_and_count_are_private(self, database_api):
        client, engine = database_api
        unread = notification()
        read = notification(read_at=datetime.now(timezone.utc))
        other = notification(recipient_id=uuid4())
        await save_rows(engine, unread, read, other)
        response = await client.get('/api/notifications', params={'unread': 'true'})
        assert [item['id'] for item in response.json()['items']] == [str(unread.id)]
        assert (await client.get('/api/notifications/unread-count')).json() == {'unread_count': 1}

    async def test_mark_one_read_is_idempotent_and_updates_badge(self, database_api):
        client, engine = database_api
        note = notification()
        await save_rows(engine, note)
        first = await client.post(f'/api/notifications/{note.id}/read')
        second = await client.post(f'/api/notifications/{note.id}/read')
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert first.json()['read_at'] is not None
        assert (await client.get('/api/notifications/unread-count')).json() == {'unread_count': 0}

    async def test_concurrent_mark_read_preserves_one_timestamp(self, database_api):
        import asyncio
        client, engine = database_api
        note = notification()
        await save_rows(engine, note)
        responses = await asyncio.gather(*(client.post(f'/api/notifications/{note.id}/read') for _ in range(3)))
        assert all(response.status_code == 200 for response in responses)
        assert len({response.json()['read_at'] for response in responses}) == 1

    async def test_mark_read_does_not_modify_other_users_notification(self, database_api):
        client, engine = database_api
        other = notification(recipient_id=uuid4())
        await save_rows(engine, other)
        response = await client.post(f'/api/notifications/{other.id}/read')
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'not_found'
        response = await client.post(f'/api/notifications/{uuid4()}/read')
        assert response.status_code == 404
        async with AsyncSession(engine) as session:
            assert (await session.get(Notification, other.id)).read_at is None

    async def test_mark_all_read_preserves_existing_dates_and_other_users(self, database_api):
        client, engine = database_api
        original = datetime.now(timezone.utc) - timedelta(days=2)
        unread = notification()
        read = notification(read_at=original)
        other = notification(recipient_id=uuid4())
        await save_rows(engine, unread, read, other)
        response = await client.post('/api/notifications/read-all')
        assert response.status_code == 200
        assert response.json()['updated_count'] == 1
        assert (await client.post('/api/notifications/read-all')).json()['updated_count'] == 0
        async with AsyncSession(engine) as session:
            assert (await session.get(Notification, unread.id)).read_at is not None
            assert (await session.get(Notification, read.id)).read_at == original
            assert (await session.get(Notification, other.id)).read_at is None
