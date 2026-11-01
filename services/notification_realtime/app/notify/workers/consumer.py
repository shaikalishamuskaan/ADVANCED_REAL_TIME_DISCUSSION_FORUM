import json
import logging
import socket
import uuid

from redis.exceptions import ResponseError

from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis_client
from app.notify.services.event_processor import process_event

logger = logging.getLogger(__name__)

STREAM_NAME = "stream:discussion"
GROUP_NAME = "notify"
DEAD_STREAM = "stream:dead"

CONSUMER_NAME = f"notify-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

MAX_DELIVERIES = 5
CLAIM_IDLE_MS = 60_000
BLOCK_MS = 5_000
BATCH_SIZE = 10


def _get_field(data: dict, name: str):
    """Support both string and byte keys."""
    return data.get(name, data.get(name.encode()))


async def ensure_consumer_group(redis, stream_name=STREAM_NAME, group_name=GROUP_NAME):
    try:
        await redis.xgroup_create(
            name=stream_name,
            groupname=group_name,
            id="0",
            mkstream=True,
        )
        logger.info("Created Redis consumer group: %s", group_name)

    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def get_delivery_count(
    redis, message_id: str, stream_name=STREAM_NAME, group_name=GROUP_NAME,
) -> int:
    pending = await redis.xpending_range(
        stream_name,
        group_name,
        min=message_id,
        max=message_id,
        count=1,
    )

    if not pending:
        return 0

    return int(_get_field(pending[0], "times_delivered") or 0)


async def send_to_dead_letter(
    redis,
    message_id: str,
    fields: dict,
    error: Exception,
    attempts: int,
    stream_name=STREAM_NAME,
    group_name=GROUP_NAME,
):
    envelope = _get_field(fields, "envelope")

    await redis.xadd(
        DEAD_STREAM,
        {
            "source_stream": stream_name,
            "source_message_id": message_id,
            "envelope": envelope or "",
            "error": str(error)[:1000],
            "attempts": str(attempts),
        },
    )

    await redis.xack(stream_name, group_name, message_id)

    logger.error(
        "Moved message %s to dead-letter stream after %s attempts",
        message_id,
        attempts,
    )


async def handle_entry(redis, message_id: str, fields: dict):
    try:
        raw_envelope = _get_field(fields, "envelope")

        if not raw_envelope:
            raise ValueError("Redis message does not contain an envelope")

        envelope = json.loads(raw_envelope)

        # Acknowledge only after the database transaction commits.
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await process_event(session, envelope)

        await redis.xack(STREAM_NAME, GROUP_NAME, message_id)

        logger.info("Successfully processed message %s", message_id)

    except Exception as exc:
        logger.exception("Failed to process message %s", message_id)

        try:
            attempts = await get_delivery_count(redis, message_id)

            if attempts >= MAX_DELIVERIES:
                await send_to_dead_letter(
                    redis,
                    message_id,
                    fields,
                    exc,
                    attempts,
                )

        except Exception:
            logger.exception(
                "Could not handle failed message %s",
                message_id,
            )


async def consume_forever():
    redis = get_redis_client()

    await ensure_consumer_group(redis)

    # Cursor used to scan pending messages with XAUTOCLAIM.
    claim_cursor = "0-0"

    logger.info("Notify consumer started: %s", CONSUMER_NAME)

    while True:
        try:
            # Reclaim messages pending for at least 60 seconds.
            result = await redis.xautoclaim(
                name=STREAM_NAME,
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                min_idle_time=CLAIM_IDLE_MS,
                start_id=claim_cursor,
                count=BATCH_SIZE,
            )

            claim_cursor = result[0]
            reclaimed_messages = result[1]

            for message_id, fields in reclaimed_messages:
                await handle_entry(redis, message_id, fields)

            if claim_cursor == "0-0":
                # Start a fresh scan on the next iteration.
                claim_cursor = "0-0"

            # Read new messages.
            messages = await redis.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=BATCH_SIZE,
                block=BLOCK_MS,
            )

            for _, entries in messages:
                for message_id, fields in entries:
                    await handle_entry(redis, message_id, fields)

        except Exception:
            logger.exception("Notify consumer loop encountered an error")