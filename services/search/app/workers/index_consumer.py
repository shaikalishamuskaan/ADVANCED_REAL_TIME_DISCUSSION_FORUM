import asyncio
import json
import logging
import socket
from uuid import uuid4

from redis.exceptions import ResponseError

from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis_client
from app.services.index_events import process_event

logger = logging.getLogger(__name__)
STREAMS = ("stream:discussion", "stream:identity")
GROUP = "search"
DEAD_STREAM = "stream:dead"
MAX_DELIVERIES = 5
CLAIM_IDLE_MS = 60_000
BATCH_SIZE = 10
BLOCK_MS = 5_000


def field(fields, name):
    return fields.get(name, fields.get(name.encode()))


class SearchConsumer:
    def __init__(self, redis=None, session_factory=None):
        self.redis = redis if redis is not None else get_redis_client()
        self.session_factory = session_factory if session_factory is not None else AsyncSessionLocal
        self.consumer_name = f"search-{socket.gethostname()}-{uuid4().hex[:8]}"
        self.claim_cursors = {stream: "0-0" for stream in STREAMS}

    async def ensure_groups(self):
        for stream in STREAMS:
            try:
                await self.redis.xgroup_create(name=stream, groupname=GROUP, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def handle_entry(self, stream, message_id, fields):
        if isinstance(stream, bytes):
            stream = stream.decode()
        try:
            raw = field(fields, "envelope")
            if not raw:
                raise ValueError("Stream entry has no envelope")
            envelope = json.loads(raw)
            async with self.session_factory() as session:
                async with session.begin():
                    await process_event(session, envelope, stream)
            await self.redis.xack(stream, GROUP, message_id)
            logger.info("stream.processed", extra={"event_id": envelope.get("event_id") if isinstance(envelope, dict) else None,
                        "message_id": message_id, "stream": stream, "consumer": GROUP})
        except Exception as exc:
            logger.exception("Search failed to process entry %s on %s", message_id, stream)
            pending = await self.redis.xpending_range(stream, GROUP, min=message_id, max=message_id, count=1)
            attempts = int(field(pending[0], "times_delivered") or 0) if pending else 0
            if attempts >= MAX_DELIVERIES:
                await self.redis.xadd(DEAD_STREAM, {
                    "source_stream": stream, "source_message_id": message_id,
                    "envelope": field(fields, "envelope") or "",
                    "error": str(exc)[:1000], "attempts": str(attempts),
                })
                await self.redis.xack(stream, GROUP, message_id)
                logger.error("stream.dead_lettered", extra={"message_id": message_id,
                             "stream": stream, "consumer": GROUP, "attempts": attempts})

    async def run_once(self):
        for stream in STREAMS:
            result = await self.redis.xautoclaim(
                name=stream, groupname=GROUP, consumername=self.consumer_name,
                min_idle_time=CLAIM_IDLE_MS, start_id=self.claim_cursors[stream], count=BATCH_SIZE,
            )
            self.claim_cursors[stream] = result[0]
            for message_id, fields in result[1]:
                await self.handle_entry(stream, message_id, fields)
        messages = await self.redis.xreadgroup(
            groupname=GROUP, consumername=self.consumer_name,
            streams={stream: ">" for stream in STREAMS}, count=BATCH_SIZE, block=BLOCK_MS,
        )
        for stream, entries in messages:
            for message_id, fields in entries:
                await self.handle_entry(stream, message_id, fields)

    async def run(self):
        while True:
            try:
                await self.ensure_groups()
                while True:
                    await self.run_once()
            except Exception:
                logger.exception("Search consumer failed; retrying")
                await asyncio.sleep(1)


async def consume_forever():
    await SearchConsumer().run()
