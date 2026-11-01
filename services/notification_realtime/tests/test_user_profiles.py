from uuid import uuid4

import httpx
import pytest

from app.clients import user_profiles


@pytest.mark.asyncio
async def test_profile_lookup_deduplicates_and_validates_identity_response(monkeypatch):
    user_id = str(uuid4())
    requests = []
    real_client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'id': user_id, 'username': 'alice', 'status': 'disabled', 'role': 'member'})
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    assert await user_profiles.get_user_profiles([user_id, user_id]) == {user_id: {'id': user_id, 'username': 'alice'}}
    assert len(requests) == 1
    settings = user_profiles.get_settings()
    assert str(requests[0].url) == f'{settings.IDENTITY_BASE_URL}/internal/users/{user_id}/status'
    assert requests[0].headers['X-Service-Key'] == settings.IDENTITY_SERVICE_KEY


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'id': str(uuid4()), 'username': 'wrong_user'}, {'id': 'invalid', 'username': 'alice'}])
async def test_bad_profile_response_is_rejected(monkeypatch, payload):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    with pytest.raises(ValueError):
        await user_profiles.get_user_profiles([str(uuid4())])


@pytest.mark.asyncio
async def test_empty_profile_lookup_needs_no_identity_request(monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError('Empty lookups must not call Identity')
    monkeypatch.setattr(httpx, 'AsyncClient', unexpected_client)
    assert await user_profiles.get_user_profiles([]) == {}
