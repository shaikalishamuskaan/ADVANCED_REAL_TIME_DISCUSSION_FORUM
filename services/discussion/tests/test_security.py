from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException

from app.core import security


@pytest.fixture
def rsa_keys(monkeypatch):
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    class FakeSettings:
        JWT_ALGORITHM = "RS256"
        JWT_ISSUER = "identity"
        JWT_AUDIENCE = "forum"

    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: FakeSettings(),
    )

    monkeypatch.setattr(
        security,
        "get_public_key",
        lambda: public_pem,
    )

    return private_pem


def create_token(private_key, **overrides):
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(uuid4()),
        "username": "test_user",
        "role": "member",
        "iss": "identity",
        "aud": "forum",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "sid": str(uuid4()),
    }

    payload.update(overrides)

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
    )


def test_valid_access_token(rsa_keys):
    token = create_token(rsa_keys)

    user = security.verify_access_token(token)

    assert user.username == "test_user"
    assert user.role == "member"


def test_refresh_style_jti_does_not_replace_required_access_session_claim(rsa_keys):
    now = datetime.now(timezone.utc)
    token = jwt.encode({"sub": str(uuid4()), "username": "test_user", "role": "member",
                        "iss": "identity", "aud": "forum", "iat": now,
                        "exp": now + timedelta(minutes=15), "jti": str(uuid4())}, rsa_keys, algorithm="RS256")
    with pytest.raises(HTTPException) as error:
        security.verify_access_token(token)
    assert error.value.status_code == 401


def test_expired_token_is_rejected(rsa_keys):
    token = create_token(
        rsa_keys,
        exp=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    with pytest.raises(HTTPException) as error:
        security.verify_access_token(token)

    assert error.value.status_code == 401


def test_wrong_issuer_is_rejected(rsa_keys):
    token = create_token(
        rsa_keys,
        iss="wrong-issuer",
    )

    with pytest.raises(HTTPException) as error:
        security.verify_access_token(token)

    assert error.value.status_code == 401


def test_wrong_audience_is_rejected(rsa_keys):
    token = create_token(
        rsa_keys,
        aud="wrong-audience",
    )

    with pytest.raises(HTTPException) as error:
        security.verify_access_token(token)

    assert error.value.status_code == 401


def test_missing_required_claim_is_rejected(rsa_keys):
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(uuid4()),
        "username": "test_user",
        "iss": "identity",
        "aud": "forum",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "sid": str(uuid4()),
    }

    token = jwt.encode(
        payload,
        rsa_keys,
        algorithm="RS256",
    )

    with pytest.raises(HTTPException) as error:
        security.verify_access_token(token)

    assert error.value.status_code == 401
