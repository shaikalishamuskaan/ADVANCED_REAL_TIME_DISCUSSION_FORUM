from functools import lru_cache
from pathlib import Path
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings


class AuthenticatedUser(BaseModel):
    user_id: UUID
    username: str
    role: str


@lru_cache
def get_public_key() -> str:
    settings = get_settings()

    key_path = Path(settings.JWT_PUBLIC_KEY_PATH)

    if not key_path.is_absolute():
        key_path = Path(__file__).resolve().parents[2] / key_path

    try:
        return key_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"JWT public key could not be loaded from: {key_path}"
        ) from exc


def verify_access_token(token: str) -> AuthenticatedUser:
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            get_public_key(),
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require": [
                    "sub",
                    "username",
                    "role",
                    "iss",
                    "aud",
                    "exp",
                    "iat",
                    "jti",
                ]
            },
        )

        return AuthenticatedUser(
            user_id=UUID(payload["sub"]),
            username=payload["username"],
            role=payload["role"],
        )

    except (InvalidTokenError, ValueError, ValidationError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthenticated",
                    "message": "Invalid or expired access token.",
                    "details": {},
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )