import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import main
from app.api.dependencies import rate_limit
from app.core.database import get_db
from app.core.redis import get_redis_client, close_redis_client
from tests.test_database_integration import database, document, save
from tests.test_search_api import token_factory

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get('RUN_SEARCH_INTEGRATION') != '1', reason='Set RUN_SEARCH_INTEGRATION=1; requires local PostgreSQL and Redis')]


@pytest_asyncio.fixture
async def real_api(database, token_factory, monkeypatch):
    engine, schema = database
    redis = get_redis_client()
    users = [uuid4(), uuid4()]
    keys = [f'se:rl:search:{user}' for user in users]
    headers = [{'Authorization': f'Bearer {token_factory(user)}'} for user in users]
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    main.app.dependency_overrides[get_db] = sessions
    monkeypatch.setattr(rate_limit, 'get_redis_client', lambda: redis)
    try:
        assert await redis.ping()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            yield client, headers, engine, redis, keys
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        # Random user IDs make these counters exclusive to this test.
        await redis.delete(*keys)
        await close_redis_client()


async def test_endpoint_returns_lld_results_with_filters_and_cursor(real_api):
    client, headers, engine, redis, keys = real_api
    now = datetime.now(timezone.utc)
    thread = document(title='Token rotation', tags='python redis', body='A token discussion', created_at=now)
    comment = document(doc_type='comment', title=None, thread_id=thread.thread_id, tags='python redis', body='<b>Token reply</b>', created_at=now + timedelta(seconds=1))
    await save(engine, thread, comment)
    response = await client.get('/api/search', params={'q': ' TOKEN ', 'limit': 1, 'tag': ' PYTHON '}, headers=headers[0])
    assert response.status_code == 200
    body = response.json()
    assert len(body['items']) == 1
    hit = body['items'][0]
    assert set(hit) == {'type', 'id', 'thread_id', 'title', 'thread_title', 'snippet', 'author_username', 'created_at'}
    assert hit['type'] == 'comment'
    assert hit['id'] == str(comment.source_id)
    assert hit['title'] is None
    assert hit['snippet'] == '<b>Token reply</b>'
    assert body['next_cursor'] is not None
    response = await client.get('/api/search', params={'q': 'token', 'limit': 1, 'cursor': body['next_cursor']}, headers=headers[0])
    assert response.status_code == 200
    assert [item['id'] for item in response.json()['items']] == [str(thread.source_id)]
    assert response.json()['next_cursor'] is None
    response = await client.get('/api/search', params={'q': 'token', 'type': 'thread'}, headers=headers[0])
    assert [item['id'] for item in response.json()['items']] == [str(thread.source_id)]


async def test_concurrent_limit_is_atomic_private_and_returns_retry_after(real_api):
    client, headers, engine, redis, keys = real_api
    async with asyncio.timeout(10):
        responses = await asyncio.gather(*(client.get('/api/search', params={'q': 'token'}, headers=headers[0]) for _ in range(35)))
    assert sum(response.status_code == 200 for response in responses) == 30
    rejected = [response for response in responses if response.status_code == 429]
    assert len(rejected) == 5
    assert all(1 <= int(response.headers['Retry-After']) <= 60 for response in rejected)
    assert await redis.get(keys[0]) == '35'
    assert 0 < await redis.ttl(keys[0]) <= 60
    other = await client.get('/api/search', params={'q': 'token'}, headers=headers[1])
    assert other.status_code == 200
    assert await redis.get(keys[1]) == '1'


async def test_real_redis_expiry_starts_a_fresh_window(real_api):
    client, headers, engine, redis, keys = real_api
    await redis.set(keys[0], 30, ex=60)
    response = await client.get('/api/search', params={'q': 'token'}, headers=headers[0])
    assert response.status_code == 429
    # Accelerate expiry of this test counter; production still uses 60 seconds.
    await redis.pexpire(keys[0], 10)
    async with asyncio.timeout(2):
        while await redis.exists(keys[0]):
            await asyncio.sleep(0.01)
    response = await client.get('/api/search', params={'q': 'token'}, headers=headers[0])
    assert response.status_code == 200
    assert await redis.get(keys[0]) == '1'
    assert 0 < await redis.ttl(keys[0]) <= 60
