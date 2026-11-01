from functools import lru_cache
from pathlib import Path
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import SERVICE_ROOT, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_public_key() -> str:
    settings = get_settings()
    key_path = Path(settings.JWT_PUBLIC_KEY_PATH)

    if not key_path.is_absolute():
        key_path = (SERVICE_ROOT / key_path).resolve()

    return key_path.read_text(encoding="utf-8")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Unauthenticated")

    settings = get_settings()

    try:
        payload = jwt.decode(
            credentials.credentials,
            get_public_key(),
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )

        user_id = UUID(payload["sub"])

    except (jwt.PyJWTError, ValueError, KeyError, OSError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {"id": user_id}