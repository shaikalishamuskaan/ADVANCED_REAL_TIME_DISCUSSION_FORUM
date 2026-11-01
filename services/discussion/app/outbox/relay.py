import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from anyio import CancelScope
from redis.exceptions import RedisError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import engine
from app.core.redis import get_redis_client
from app.models.outbox import Outbox

logger = logging.getLogger(__name__)
# A stable, service-specific session lock shared by every Discussion relay.
ADVISORY_LOCK_KEY = 0x444953435553


async def publish_row(redis, row: Outbox):
    # Older report rows used event_type. Preserve their stable ID while sending
    # the canonical envelope accepted by every stream consumer.
    envelope = dict(row.payload)
    envelope_type = envelope.get("type", envelope.get("event_type"))
    if envelope.get("event_id") != str(row.id) or envelope_type != row.event_type:
        raise ValueError("Outbox envelope does not match its row")
    envelope["type"] = envelope_type
    envelope.pop("event_type", None)
    payload = envelope["payload"]
    allowed = {"thread.created", "thread.updated", "thread.deleted", "comment.created", "comment.updated", "comment.deleted", "like.changed", "report.created", "activity.recorded"}
    if row.event_type not in allowed or not isinstance(payload, dict):
        raise ValueError("Unsupported Discussion event")
    thread_id = None
    if row.event_type.startswith(("thread.", "comment.")) or row.event_type == "like.changed":
        thread_id = str(UUID(str(payload["thread_id"])))
    if row.event_type == "like.changed" and payload.get("target_type") not in {"thread", "comment"}:
        raise ValueError("Invalid like target")
    if row.event_type != "like.changed":
        await redis.xadd("stream:discussion", {"envelope": json.dumps(envelope)}, maxlen=100_000, approximate=True)
    channel = None
    if row.event_type.startswith("thread."):
        channel = "ws:global"
    elif row.event_type.startswith("comment."):
        channel = f"ws:thread:{thread_id}"
    elif row.event_type == "like.changed":
        channel = "ws:global" if payload["target_type"] == "thread" else f"ws:thread:{thread_id}"
    if channel:
        await redis.publish(channel, json.dumps({"type": "event", "event": row.event_type, "thread_id": thread_id, "data": payload}))


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
            logger.error("Discussion outbox oldest unpublished row is %.1f seconds old", age)

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
                        logger.info("Discussion outbox relay acquired leadership")
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
            logger.exception("Discussion outbox relay failed; unpublished rows will be retried")
        await asyncio.sleep(interval)
