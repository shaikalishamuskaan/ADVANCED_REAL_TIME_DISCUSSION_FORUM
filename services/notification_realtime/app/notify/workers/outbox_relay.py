import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from anyio import CancelScope
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import engine
from app.core.redis import get_redis_client
from app.models.outbox import Outbox

logger = logging.getLogger(__name__)
# A stable, service-specific session lock shared by every Notification relay.
ADVISORY_LOCK_KEY = 0x4E4F54494659


class NotificationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    data: dict


async def publish_row(redis, row: Outbox):
    if row.event_type != "notification.created":
        raise ValueError("Unsupported Notification outbox event")
    target = row.payload["target"]
    if not isinstance(target, str) or not target.startswith("ws:user:"):
        raise ValueError("Notification outbox target must be a user room")
    user_id = UUID(target.removeprefix("ws:user:"))
    if target != f"ws:user:{user_id}":
        raise ValueError("Notification outbox target must contain a canonical user ID")
    message = NotificationMessage.model_validate(row.payload["event"])
    if message.type != "notification":
        raise ValueError("Notification outbox message must have type notification")
    # PUBLISH returning zero is successful: offline users read persisted notifications.
    await redis.publish(target, message.model_dump_json())


async def publish_pending_batch(session: AsyncSession, redis, batch_size: int) -> int:
    async with session.begin():
        result = await session.scalars(
            select(Outbox)
            .where(Outbox.published_at.is_(None))
            .order_by(Outbox.created_at, Outbox.id)
            .limit(batch_size)
        )
        rows = result.all()
    if rows:
        age = (datetime.now(timezone.utc) - rows[0].created_at).total_seconds()
        if age > 60:
            logger.error("Notification outbox oldest unpublished row is %.1f seconds old", age)

    published = 0
    for row in rows:
        # A failure stops the batch, preserving creation order. A crash between
        # PUBLISH and commit can repeat this message, as required by the LLD.
        await publish_row(redis, row)
        async with session.begin():
            await session.execute(
                update(Outbox)
                .where(Outbox.id == row.id, Outbox.published_at.is_(None))
                .values(published_at=func.now())
            )
        published += 1
    return published


async def run_outbox_relay():
    settings = get_settings()
    redis = get_redis_client()
    interval = settings.OUTBOX_RELAY_INTERVAL_MS / 1000
    while True:
        try:
            # Keep a dedicated physical connection for the session advisory lock.
            async with engine.connect() as connection:
                locked = None
                try:
                    locked = bool(await connection.scalar(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY},
                    ))
                    await connection.commit()
                    if locked:
                        logger.info("Notification outbox relay acquired leadership")
                        while True:
                            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                                await publish_pending_batch(session, redis, settings.OUTBOX_BATCH_SIZE)
                            await asyncio.sleep(interval)
                finally:
                    # Never return a locked PostgreSQL session to the connection pool.
                    with CancelScope(shield=True):
                        try:
                            if locked is None:
                                # Cancellation during acquisition leaves ownership uncertain.
                                await connection.invalidate()
                            elif locked:
                                await connection.rollback()
                                await connection.execute(
                                    text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY},
                                )
                                await connection.commit()
                        except BaseException:
                            await connection.invalidate()
                            raise
        except (RedisError, SQLAlchemyError, ValueError, KeyError, TypeError):
            logger.exception("Notification outbox relay failed; unpublished rows will be retried")
        await asyncio.sleep(interval)
