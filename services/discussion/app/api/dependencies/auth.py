from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import (
    AuthenticatedUser,
    verify_access_token,
)


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> AuthenticatedUser:

    if credentials is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "unauthenticated",
                    "message": "Authentication credentials are required.",
                    "details": {},
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_access_token(credentials.credentials)