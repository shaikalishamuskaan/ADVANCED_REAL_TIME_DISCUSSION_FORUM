import asyncio
import json
import logging

from app.core.redis import get_redis_client
from app.realtime.connection_manager import manager

logger = logging.getLogger(__name__)


async def listen_to_redis():
    redis = get_redis_client()
    pubsub = redis.pubsub()

    try:
        # Subscribe to all realtime channels.
        await pubsub.psubscribe("ws:*")

        logger.info("Subscribed to Redis Pub/Sub pattern ws:*")

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )

            if message is None:
                await asyncio.sleep(0.01)
                continue

            channel = message["channel"]
            data = message["data"]

            try:
                payload = json.loads(data)

                await manager.publish_to_room(
                    channel=channel,
                    message=payload,
                )

            except (ValueError, TypeError):
                logger.exception(
                    "Invalid Pub/Sub message received on %s",
                    channel,
                )

    finally:
        await pubsub.aclose()