import json
from uuid import uuid4

import httpx
import pytest

from app.clients import identity


@pytest.fixture
def lookup(monkeypatch):
    identity._username_cache.clear()
    state = {'users': {}, 'requests': [], 'now': 100.0, 'error': None, 'payload': None}
    real_client = httpx.AsyncClient
    def respond(request):
        state['requests'].append(request)
        if state['error'] is not None:
            raise state['error']
        if state['payload'] is not None:
            return httpx.Response(200, json=state['payload'])
        names = json.loads(request.content)['usernames']
        return httpx.Response(200, json=[state['users'][name.lower()] for name in names if name.lower() in state['users']])
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(identity, 'monotonic', lambda: state['now'])
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    yield state
    identity._username_cache.clear()


def add_user(state, username):
    user = {'id': str(uuid4()), 'username': username}
    state['users'][username.lower()] = user
    return user


def requested_names(state, index=-1):
    return json.loads(state['requests'][index].content)['usernames']


@pytest.mark.asyncio
async def test_empty_lookup_does_not_call_identity(lookup):
    assert await identity.resolve_usernames([]) == {}
    assert not lookup['requests']


@pytest.mark.asyncio
async def test_lookup_uses_existing_identity_endpoint_and_service_key(lookup):
    user = add_user(lookup, 'Alice')
    assert await identity.resolve_usernames(['Alice']) == {'alice': user}
    request = lookup['requests'][0]
    settings = identity.get_settings()
    assert request.method == 'POST'
    assert str(request.url) == f'{settings.IDENTITY_BASE_URL}/internal/users/resolve'
    assert request.headers['X-Service-Key'] == settings.IDENTITY_SERVICE_KEY
    assert requested_names(lookup) == ['Alice']


@pytest.mark.asyncio
async def test_cache_is_case_insensitive_and_deduplicates_request(lookup):
    user = add_user(lookup, 'Alice')
    assert await identity.resolve_usernames(['Alice', 'ALICE', 'alice']) == {'alice': user}
    assert requested_names(lookup) == ['Alice']
    assert await identity.resolve_usernames(['aLiCe']) == {'alice': user}
    assert len(lookup['requests']) == 1


@pytest.mark.asyncio
async def test_partial_cache_hit_only_fetches_missing_names(lookup):
    alice = add_user(lookup, 'Alice')
    bob = add_user(lookup, 'Bob')
    await identity.resolve_usernames(['Alice'])
    assert await identity.resolve_usernames(['ALICE', 'Bob']) == {'alice': alice, 'bob': bob}
    assert requested_names(lookup) == ['Bob']
    assert len(lookup['requests']) == 2


@pytest.mark.asyncio
async def test_cache_expires_at_sixty_seconds_without_sliding_on_hits(lookup):
    original = add_user(lookup, 'Alice')
    await identity.resolve_usernames(['alice'])
    lookup['now'] += 59.999
    assert await identity.resolve_usernames(['Alice']) == {'alice': original}
    assert len(lookup['requests']) == 1
    changed = add_user(lookup, 'Alice')
    lookup['now'] = 160.0
    assert await identity.resolve_usernames(['alice']) == {'alice': changed}
    assert len(lookup['requests']) == 2


@pytest.mark.asyncio
async def test_unknown_user_is_not_negatively_cached(lookup):
    assert await identity.resolve_usernames(['newuser']) == {}
    user = add_user(lookup, 'newuser')
    assert await identity.resolve_usernames(['newuser']) == {'newuser': user}
    assert len(lookup['requests']) == 2


@pytest.mark.asyncio
async def test_network_failure_is_retryable_and_keeps_existing_valid_cache(lookup):
    alice = add_user(lookup, 'Alice')
    bob = add_user(lookup, 'Bob')
    await identity.resolve_usernames(['Alice'])
    lookup['error'] = httpx.ConnectError('Identity unavailable')
    with pytest.raises(httpx.ConnectError):
        await identity.resolve_usernames(['alice', 'bob'])
    assert await identity.resolve_usernames(['alice']) == {'alice': alice}
    lookup['error'] = None
    assert await identity.resolve_usernames(['bob']) == {'bob': bob}
    assert len(lookup['requests']) == 3


@pytest.mark.asyncio
async def test_expired_cache_does_not_hide_identity_failure(lookup):
    add_user(lookup, 'Alice')
    await identity.resolve_usernames(['alice'])
    lookup['now'] += 60
    lookup['error'] = httpx.ConnectError('Identity unavailable')
    with pytest.raises(httpx.ConnectError):
        await identity.resolve_usernames(['alice'])
    assert 'alice' not in identity._username_cache


@pytest.mark.asyncio
async def test_http_failure_does_not_become_cached_miss(lookup):
    user = add_user(lookup, 'Alice')
    request = httpx.Request('POST', 'http://identity/internal/users/resolve')
    lookup['error'] = httpx.HTTPStatusError('Service error', request=request, response=httpx.Response(503, request=request))
    with pytest.raises(httpx.HTTPStatusError):
        await identity.resolve_usernames(['alice'])
    lookup['error'] = None
    assert await identity.resolve_usernames(['alice']) == {'alice': user}
    assert len(lookup['requests']) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, [{'id': 'invalid', 'username': 'Alice'}], [{'id': str(uuid4()), 'username': 'bad-name'}]])
async def test_invalid_response_is_not_cached(lookup, payload):
    user = add_user(lookup, 'Alice')
    lookup['payload'] = payload
    with pytest.raises(ValueError):
        await identity.resolve_usernames(['alice'])
    assert not identity._username_cache
    lookup['payload'] = None
    assert await identity.resolve_usernames(['alice']) == {'alice': user}


@pytest.mark.asyncio
async def test_validation_is_atomic_before_caching_response(lookup):
    user = add_user(lookup, 'Alice')
    lookup['payload'] = [user, {'id': 'invalid', 'username': 'Bob'}]
    with pytest.raises(ValueError):
        await identity.resolve_usernames(['alice', 'bob'])
    assert not identity._username_cache


@pytest.mark.asyncio
async def test_response_cannot_add_unrequested_names_to_cache(lookup):
    alice = add_user(lookup, 'Alice')
    bob = add_user(lookup, 'Bob')
    lookup['payload'] = [alice, bob]
    assert await identity.resolve_usernames(['alice']) == {'alice': alice}
    assert 'bob' not in identity._username_cache


@pytest.mark.asyncio
async def test_returned_records_cannot_mutate_cached_results(lookup):
    alice = add_user(lookup, 'Alice')
    first = await identity.resolve_usernames(['alice'])
    first['alice']['id'] = 'changed'
    second = await identity.resolve_usernames(['alice'])
    assert second == {'alice': alice}
    second['alice']['username'] = 'changed'
    assert await identity.resolve_usernames(['alice']) == {'alice': alice}


@pytest.mark.asyncio
async def test_memory_cache_is_bounded_and_evicts_least_recently_used(lookup, monkeypatch):
    monkeypatch.setattr(identity, 'USERNAME_CACHE_MAX_ENTRIES', 2)
    for name in ['alice', 'bob', 'charlie']:
        add_user(lookup, name)
    await identity.resolve_usernames(['alice', 'bob'])
    await identity.resolve_usernames(['alice'])
    await identity.resolve_usernames(['charlie'])
    assert set(identity._username_cache) == {'alice', 'charlie'}
    await identity.resolve_usernames(['bob'])
    assert requested_names(lookup) == ['bob']
    assert len(identity._username_cache) == 2
    assert len(lookup['requests']) == 3
