import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings


async def require_search_service(
    x_service_key: Annotated[str | None, Header()] = None,
) -> None:
    expected_key = get_settings().SEARCH_SERVICE_KEY

    if (
        not expected_key
        or not x_service_key
        or not secrets.compare_digest(x_service_key, expected_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthorized_service",
                    "message": "Invalid service credentials.",
                    "details": {},
                }
            },
        )