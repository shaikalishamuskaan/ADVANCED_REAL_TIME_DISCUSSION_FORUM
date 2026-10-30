
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from config.settings import load_jwt_key


def create_access_token(user, session_id):
    """Create an access token associated with a refresh-token session."""
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "sid": str(session_id),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(
            seconds=settings.ACCESS_TOKEN_TTL_SECONDS
        ),
    }

    private_key = load_jwt_key(settings.JWT_PRIVATE_KEY_PATH)

    return jwt.encode(payload, private_key, algorithm="RS256")



def create_refresh_token(user):
    """Create a refresh token and store only its jti in the database."""
    from auth_flow.models import RefreshToken

    now = datetime.now(timezone.utc)
    jti = uuid.uuid4()
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)

    payload = {
        "sub": str(user.id),
        "jti": str(jti),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": expires_at,
    }

    RefreshToken.objects.create(
        jti=jti,
        user=user,
        expires_at=expires_at,
    )

    private_key = load_jwt_key(settings.JWT_PRIVATE_KEY_PATH)

    return jwt.encode(payload, private_key, algorithm="RS256")


def decode_refresh_token(token):
    """Verify a refresh token's RS256 signature and standard claims."""
    public_key = load_jwt_key(settings.JWT_PUBLIC_KEY_PATH)

    return jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["sub", "jti", "iss", "aud", "iat", "exp"]},
    )
