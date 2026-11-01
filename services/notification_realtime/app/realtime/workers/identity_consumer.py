import asyncio
import json
import logging
import socket
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.core.redis import get_redis_client
from app.notify.workers.consumer import (
    BATCH_SIZE,
    BLOCK_MS,
    CLAIM_IDLE_MS,
    MAX_DELIVERIES,
    _get_field,
    ensure_consumer_group,
    get_delivery_count,
    send_to_dead_letter,
)

logger = logging.getLogger(__name__)
STREAM_NAME = "stream:identity"
GROUP_NAME = "realtime-cache"
CONSUMER_NAME = f"realtime-cache-{socket.gethostname()}-{uuid4().hex[:8]}"
STATUS_EVENTS = {"user.role_changed", "user.disabled", "user.enabled"}


class IdentityEvent(BaseModel):
    event_id: UUID
    type: str
    payload: dict


async def process_identity_event(redis, envelope: dict):
    event = IdentityEvent.model_validate(envelope)
    if event.type not in STATUS_EVENTS:
        return
    user_id = UUID(str(event.payload["user_id"]))
    # These operations are safe to repeat after a crash or redelivery.
    await redis.delete(f"rt:user_status:{user_id}")
    if event.type == "user.disabled":
        # Every gateway receives the existing Identity envelope on the user room.
        # The listener handles it internally; it is never sent to the browser.
        await redis.publish(f"ws:user:{user_id}", json.dumps(envelope))


async def handle_entry(redis, message_id: str, fields: dict):
    try:
        raw = _get_field(fields, "envelope")
        if not raw:
            raise ValueError("Redis message does not contain an envelope")
        await process_identity_event(redis, json.loads(raw))
        # Both cache deletion and disable fan-out must succeed before ACK.
        await redis.xack(STREAM_NAME, GROUP_NAME, message_id)
    except Exception as exc:
        logger.exception("Failed to process Identity message %s", message_id)
        attempts = await get_delivery_count(redis, message_id, STREAM_NAME, GROUP_NAME)
        if attempts >= MAX_DELIVERIES:
            await send_to_dead_letter(
                redis, message_id, fields, exc, attempts, STREAM_NAME, GROUP_NAME,
            )


async def consume_identity_forever():
    redis = get_redis_client()
    claim_cursor = "0-0"
    while True:
        try:
            await ensure_consumer_group(redis, STREAM_NAME, GROUP_NAME)
            while True:
                result = await redis.xautoclaim(
                    name=STREAM_NAME,
                    groupname=GROUP_NAME,
                    consumername=CONSUMER_NAME,
                    min_idle_time=CLAIM_IDLE_MS,
                    start_id=claim_cursor,
                    count=BATCH_SIZE,
                )
                claim_cursor = result[0]
                for message_id, fields in result[1]:
                    await handle_entry(redis, message_id, fields)
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
            logger.exception("Identity consumer loop encountered an error")
            await asyncio.sleep(1)
