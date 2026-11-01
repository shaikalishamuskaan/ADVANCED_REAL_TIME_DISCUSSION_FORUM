import json
import logging
import socket
import time
import uuid
from datetime import datetime

import redis

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from audit.models import ActivityLog, ProcessedEvent


logger = logging.getLogger(__name__)

DISCUSSION_STREAM = "stream:discussion"
CONSUMER_GROUP = "audit"

# Keep this stable across all instances of this consumer.
# It is used for event deduplication in ProcessedEvent.
CONSUMER_KEY = "audit"

# Each running process gets its own Redis consumer identity.
CONSUMER_NAME = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

PENDING_IDLE_TIME_MS = 60_000
READ_COUNT = 10
BLOCK_TIME_MS = 5_000

# These valid events share our stream but are owned by other consumers.
IGNORED_EVENT_TYPES = frozenset({
    "thread.created", "thread.updated", "thread.deleted",
    "comment.created", "comment.updated", "comment.deleted",
    "report.created", "like.changed",
})


def process_event(envelope):
    """
    Store one activity.recorded event exactly once in the identity database.

    The ProcessedEvent record and ActivityLog record are written in
    the same database transaction.
    """
    if envelope.get("type") != "activity.recorded":
        raise ValueError(
            f"Unsupported event type: {envelope.get('type')}"
        )

    event_id = uuid.UUID(envelope["event_id"])
    payload = envelope["payload"]

    actor_id = uuid.UUID(payload["actor_id"])
    target_id = uuid.UUID(payload["target_id"])

    metadata = dict(payload.get("metadata") or {})
    metadata["actor_role"] = payload["actor_role"]

    with transaction.atomic():
        try:
            # The nested transaction creates a savepoint. If the unique
            # constraint detects a duplicate, only this savepoint rolls back.
            with transaction.atomic():
                ProcessedEvent.objects.create(
                    event_id=event_id,
                    consumer=CONSUMER_KEY,
                )
        except IntegrityError:
            logger.info(
                "Event %s was already processed by %s.",
                event_id,
                CONSUMER_KEY,
            )
            return False

        ActivityLog.objects.create(
            actor_id=actor_id,
            action=payload["action"],
            target_type=payload["target_type"],
            target_id=target_id,
            metadata=metadata,
        )

    return True


class AuditEventConsumer:
    def __init__(self):
        self.redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=5,
        )
    def ensure_consumer_group(self):
        try:
            self.redis_client.xgroup_create(
                name=DISCUSSION_STREAM,
                groupname=CONSUMER_GROUP,
                id="0-0",
                mkstream=True,
            )
            logger.info(
                "Created Redis consumer group '%s' for '%s'.",
                CONSUMER_GROUP,
                DISCUSSION_STREAM,
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
            logger.info(
                "Redis consumer group '%s' already exists.",
                CONSUMER_GROUP,
            )

    @staticmethod
    def decode_message(fields):
        raw_envelope = fields.get("envelope")

        if not raw_envelope:
            raise ValueError("Redis message does not contain an envelope.")

        envelope = json.loads(raw_envelope)
        if not isinstance(envelope, dict):
            raise ValueError("Event envelope must be an object.")
        uuid.UUID(envelope["event_id"])
        if envelope.get("version") != 1 or envelope.get("producer") != "discussion":
            raise ValueError("Unsupported Discussion envelope version or producer.")
        timestamp = envelope["occurred_at"]
        if not isinstance(timestamp, str):
            raise ValueError("Event timestamp must be a string.")
        occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if occurred_at.tzinfo is None or not isinstance(envelope.get("payload"), dict):
            raise ValueError("Event requires a timezone-aware timestamp and object payload.")
        return envelope

    def acknowledge(self, message_id):
        self.redis_client.xack(
            DISCUSSION_STREAM,
            CONSUMER_GROUP,
            message_id,
        )

    def handle_message(self, message_id, fields):
        envelope = self.decode_message(fields)

        if envelope.get("type") in IGNORED_EVENT_TYPES:
            # XACK affects only the audit group's pending list. Search and
            # Notify still receive and acknowledge their own copies.
            self.acknowledge(message_id)
            logger.debug("Acknowledged non-audit event %s.", envelope["event_id"])
            return

        # The database transaction must finish before Redis is acknowledged.
        process_event(envelope)

        self.acknowledge(message_id)

        logger.info(
            "Processed and acknowledged event %s (Redis message %s).",
            envelope["event_id"],
            message_id,
        )

    def reclaim_pending_messages(self):
        """
        Recover messages that have been pending for at least 60 seconds.
        """
        next_id, messages, deleted_ids = self.redis_client.xautoclaim(
            name=DISCUSSION_STREAM,
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            min_idle_time=PENDING_IDLE_TIME_MS,
            start_id="0-0",
            count=READ_COUNT,
        )

        for message_id, fields in messages:
            self.handle_message(message_id, fields)

        return len(messages)

    def read_new_messages(self):
        results = self.redis_client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            streams={DISCUSSION_STREAM: ">"},
            count=READ_COUNT,
            block=BLOCK_TIME_MS,
        )

        processed_count = 0

        for stream_name, messages in results:
            for message_id, fields in messages:
                self.handle_message(message_id, fields)
                processed_count += 1

        return processed_count

    def close(self):
        self.redis_client.close()


class Command(BaseCommand):
    help = "Consume activity.recorded events from the discussion stream."

    def handle(self, *args, **options):
        consumer = AuditEventConsumer()

        try:
            consumer.ensure_consumer_group()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Audit consumer started as {CONSUMER_NAME}."
                )
            )

            while True:
                try:
                    reclaimed = consumer.reclaim_pending_messages()
                    processed = consumer.read_new_messages()

                    if reclaimed or processed:
                        logger.info(
                            "Consumer cycle complete: %s reclaimed, "
                            "%s new messages processed.",
                            reclaimed,
                            processed,
                        )

                except redis.RedisError:
                    logger.exception(
                        "Redis error while consuming discussion events."
                    )
                    time.sleep(1)

                except (ValueError, KeyError, TypeError):
                    # Do not acknowledge an invalid event. It remains
                    # pending so it is not silently discarded.
                    logger.exception(
                        "Invalid event encountered. It remains pending."
                    )
                    time.sleep(1)

        except KeyboardInterrupt:
            self.stdout.write("\nAudit consumer stopped.")

        except Exception as exc:
            raise CommandError(
                f"Audit consumer could not start: {exc}"
            ) from exc

        finally:
            consumer.close()
