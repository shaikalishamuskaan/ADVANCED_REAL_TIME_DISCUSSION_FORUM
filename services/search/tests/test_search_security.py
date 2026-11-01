from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from redis.exceptions import ConnectionError

from app.api.dependencies import auth
from app.api.dependencies.rate_limit import enforce_search_limit


@pytest.fixture
def jwt_tokens(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, 'get_public_key', lambda: key.public_key())
    settings = auth.get_settings()
    claims = dict(sub=str(uuid4()), exp=int(datetime.now(timezone.utc).timestamp()) + 60,
                  iss=settings.JWT_ISSUER, aud=settings.JWT_AUDIENCE)
    return key, claims


def test_valid_rs256_token(jwt_tokens):
    key, claims = jwt_tokens
    assert str(auth.verify_access_token(jwt.encode(claims, key, algorithm='RS256'))['id']) == claims['sub']


@pytest.mark.parametrize('change', [{'exp': 1}, {'iss': 'wrong'}, {'aud': 'wrong'}, {'sub': 'invalid'}])
def test_invalid_jwt_claims(jwt_tokens, change):
    key, claims = jwt_tokens
    claims.update(change)
    with pytest.raises(HTTPException) as exc:
        auth.verify_access_token(jwt.encode(claims, key, algorithm='RS256'))
    assert exc.value.status_code == 401


@pytest.mark.parametrize('algorithm', ['HS256', 'none', 'RS256'])
def test_wrong_algorithm_and_tampered_signature(jwt_tokens, algorithm):
    key, claims = jwt_tokens
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048) if algorithm == 'RS256' else ('test-only-secret-at-least-32-characters' if algorithm == 'HS256' else None)
    with pytest.raises(HTTPException) as exc:
        auth.verify_access_token(jwt.encode(claims, wrong_key, algorithm=algorithm))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize('credentials', [None, HTTPAuthorizationCredentials(scheme='Basic', credentials='bad')])
async def test_missing_or_wrong_authentication(credentials):
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_search_rate_limit_allows_thirty_requests():
    redis = AsyncMock()
    redis.eval.side_effect = [[index, 60] for index in range(1, 32)]
    key = f'test:search-rate:{uuid4()}'
    for _ in range(30):
        await enforce_search_limit(redis, key)
    with pytest.raises(HTTPException) as exc:
        await enforce_search_limit(redis, key)
    assert exc.value.status_code == 429
    assert exc.value.headers == {'Retry-After': '60'}
    assert redis.eval.call_args.args[1:] == (1, key, 60)


@pytest.mark.asyncio
async def test_rate_limit_dependency_failure_is_closed():
    redis = AsyncMock()
    redis.eval.side_effect = ConnectionError('Unavailable')
    with pytest.raises(HTTPException) as exc:
        await enforce_search_limit(redis, 'test:search-rate:unavailable')
    assert exc.value.status_code == 503
    assert exc.value.detail['error']['code'] == 'dependency_unavailable'
