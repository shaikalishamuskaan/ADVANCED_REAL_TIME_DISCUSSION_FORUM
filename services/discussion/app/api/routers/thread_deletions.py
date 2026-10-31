from types import SimpleNamespace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.write_access import write_access
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import AuthenticatedUser
from app.services.thread_delete_service import delete_thread

router = APIRouter()


@router.delete(
    "/api/forum/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_thread_endpoint(
    thread_id: UUID,
    current_user: Annotated[
        AuthenticatedUser,
        Depends(write_access("thread_delete", 30)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis=Depends(get_redis),
):
    actor = SimpleNamespace(
        user_id=current_user.user_id,
        username=current_user.username,
        role=current_user.role,
        status="active",
    )

    try:
        deleted_at = await delete_thread(
            db=db,
            thread_id=thread_id,
            actor=actor,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "forbidden",
                "message": str(exc),
            },
        ) from exc

    if deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "Thread not found.",
            },
        )

    # Cache invalidation happens after the database commit.
    # Redis failure must not undo or fail the successful deletion.
    try:
        await redis.delete(f"ds:thread:{thread_id}")
        await redis.incr("ds:threads:ver")
    except RedisError:
        pass

    return None