import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.outbox import Outbox
from app.models.processed_event import ProcessedEvent

logger = logging.getLogger(__name__)
DAILY_INTERVAL_SECONDS = 24 * 60 * 60
RETRY_INTERVAL_SECONDS = 60
PROCESSED_EVENT_RETENTION_DAYS = 14


async def cleanup_published_outbox(
    session: AsyncSession,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    if retention_days <= 0:
        raise ValueError("Outbox retention must be positive")
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Cleanup time must include a timezone")
    cutoff = now - timedelta(days=retention_days)
    result = await session.execute(
        delete(Outbox).where(
            Outbox.published_at.is_not(None),
            Outbox.published_at < cutoff,
        )
    )
    return result.rowcount


async def cleanup_processed_events(
    session: AsyncSession,
    now: datetime | None = None,
) -> int:
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Cleanup time must include a timezone")
    result = await session.execute(
        delete(ProcessedEvent).where(
            ProcessedEvent.processed_at < now - timedelta(days=PROCESSED_EVENT_RETENTION_DAYS),
        )
    )
    return result.rowcount


async def run_cleanup_forever():
    while True:
        delay = DAILY_INTERVAL_SECONDS
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    now = datetime.now(timezone.utc)
                    deleted = await cleanup_published_outbox(
                        session, get_settings().OUTBOX_RETENTION_DAYS, now,
                    )
                    processed_deleted = await cleanup_processed_events(session, now)
            logger.info(
                "Notification cleanup removed %s published outbox rows and %s processed events",
                deleted, processed_deleted,
            )
        except (SQLAlchemyError, ValueError):
            logger.exception("Notification cleanup failed; transaction rolled back")
            delay = RETRY_INTERVAL_SECONDS
        await asyncio.sleep(delay)
