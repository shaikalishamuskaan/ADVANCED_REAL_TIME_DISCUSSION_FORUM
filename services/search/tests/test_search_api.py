from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from redis.exceptions import ConnectionError
from sqlalchemy.exc import SQLAlchemyError

from app import main
from app.api.dependencies import auth, rate_limit
from app.core.database import get_db


@pytest.fixture
def token_factory(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, 'get_public_key', lambda: private.public_key())
    settings = auth.get_settings()
    def token(user_id=None, **changes):
        claims = dict(sub=str(user_id or uuid4()), exp=int(datetime.now(timezone.utc).timestamp()) + 60,
                      iss=settings.JWT_ISSUER, aud=settings.JWT_AUDIENCE)
        claims.update(changes)
        return jwt.encode(claims, private, algorithm='RS256')
    return token


@pytest_asyncio.fixture
async def endpoint(monkeypatch, token_factory):
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.scalars.return_value = result
    async def database():
        yield session
    main.app.dependency_overrides[get_db] = database
    redis = AsyncMock()
    redis.eval.return_value = [1, 60]
    monkeypatch.setattr(rate_limit, 'get_redis_client', lambda: redis)
    user = uuid4()
    headers = {'Authorization': f'Bearer {token_factory(user)}'}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            yield client, headers, session, redis, user
    finally:
        main.app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_authenticated_empty_search_uses_approved_private_rate_key(endpoint):
    client, headers, session, redis, user = endpoint
    response = await client.get('/api/search', params={'q': 'token'}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {'items': [], 'next_cursor': None}
    assert redis.eval.call_args.args[1:] == (1, f'se:rl:search:{user}', 60)
    session.scalars.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('authorization', [None, 'Bearer invalid', 'Basic invalid'])
async def test_unauthenticated_search_never_touches_redis_or_database(endpoint, authorization):
    client, _, session, redis, user = endpoint
    headers = {'Authorization': authorization} if authorization else {}
    response = await client.get('/api/search', params={'q': 'token'}, headers=headers)
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'unauthenticated'
    redis.eval.assert_not_awaited()
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'exp': 1}, {'iss': 'wrong'}, {'aud': 'wrong'}])
async def test_invalid_jwt_is_rejected_by_endpoint(endpoint, token_factory, changes):
    client, _, session, redis, user = endpoint
    response = await client.get('/api/search', params={'q': 'token'}, headers={'Authorization': f'Bearer {token_factory(user, **changes)}'})
    assert response.status_code == 401
    session.scalars.assert_not_awaited()
    redis.eval.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('params', [{}, {'q': 'a'}, {'q': 'x'*101}, {'q': 'token', 'type': 'invalid'}, {'q': 'token', 'limit': 51}, {'q': 'token', 'tag': 'bad tag'}])
async def test_invalid_query_is_400_with_lld_error(endpoint, params):
    client, headers, session, redis, user = endpoint
    response = await client.get('/api/search', params=params, headers=headers)
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'validation_error'
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_cursor_is_400(endpoint):
    client, headers, session, redis, user = endpoint
    response = await client.get('/api/search', params={'q': 'token', 'cursor': 'not-valid!'}, headers=headers)
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'invalid_cursor'
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_blocks_query_and_returns_retry_after(endpoint):
    client, headers, session, redis, user = endpoint
    redis.eval.return_value = [31, 17]
    response = await client.get('/api/search', params={'q': 'token'}, headers=headers)
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '17'
    assert response.json()['error']['code'] == 'rate_limited'
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_failure_fails_closed(endpoint):
    client, headers, session, redis, user = endpoint
    redis.eval.side_effect = ConnectionError('Private connection details')
    response = await client.get('/api/search', params={'q': 'token'}, headers=headers)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'dependency_unavailable'
    assert 'Private' not in response.text
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_failure_is_safe_503(endpoint):
    client, headers, session, redis, user = endpoint
    session.scalars.side_effect = SQLAlchemyError('Private database details')
    response = await client.get('/api/search', params={'q': 'token'}, headers=headers)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'dependency_unavailable'
    assert 'Private' not in response.text
