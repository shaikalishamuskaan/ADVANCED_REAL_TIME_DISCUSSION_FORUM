import json
import logging

import redis

from django.conf import settings
from django.db import connections
from django.utils import timezone

from audit.models import Outbox
from datetime import timezone as datetime_timezone

logger = logging.getLogger(__name__)

IDENTITY_STREAM = "stream:identity"
STREAM_MAX_LENGTH = 50_000

# Stable PostgreSQL advisory lock key for the Identity relay.
# This is an implementation constant; all Identity relay instances
# must use the same value.
ADVISORY_LOCK_KEY = 0x4944454E54495459


class OutboxRelay:
    def __init__(self):
        self.redis_client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        self.batch_size = settings.OUTBOX_BATCH_SIZE
        self.last_batch_failed = False

    @staticmethod
    def build_envelope(outbox_row):
        occurred_at = (
        outbox_row.created_at
        .astimezone(datetime_timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

        return {
            "event_id": str(outbox_row.id),
            "type": outbox_row.event_type,
            "version": 1,
            "occurred_at": occurred_at,
            "producer": "identity",
            "payload": outbox_row.payload,
        }

    def publish_row(self, outbox_row):
        envelope = self.build_envelope(outbox_row)

        self.redis_client.xadd(
            IDENTITY_STREAM,
            {
                "envelope": json.dumps(
                    envelope,
                    separators=(",", ":"),
                )
            },
            maxlen=STREAM_MAX_LENGTH,
            approximate=True,
        )

        # Mark the row published only after Redis confirms XADD.
        Outbox.objects.filter(
            id=outbox_row.id,
            published_at__isnull=True,
        ).update(published_at=timezone.now())

    def publish_pending_batch(self):
        self.last_batch_failed = False

        rows = list(
            Outbox.objects.filter(published_at__isnull=True)
            .order_by("created_at", "id")[:self.batch_size]
        )

        published_count = 0

        for row in rows:
            try:
                self.publish_row(row)
                published_count += 1

            except redis.RedisError:
                self.last_batch_failed = True

                logger.exception(
                    "Redis publication failed for Outbox event %s. "
                    "Stopping this batch; the event will be retried.",
                    row.id,
                )
                break

        return published_count

    def close(self):
        self.redis_client.close()


def acquire_relay_lock():
    """
    Acquire a PostgreSQL session-level advisory lock.

    Keep this database connection open while the relay is running.
    """
    connection = connections["default"]
    connection.ensure_connection()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s)",
            [ADVISORY_LOCK_KEY],
        )
        acquired = cursor.fetchone()[0]

    return acquired


def release_relay_lock():
    connection = connections["default"]

    if connection.connection is None:
        return

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s)",
            [ADVISORY_LOCK_KEY],
        )
        released = cursor.fetchone()[0]

    if not released:
        logger.warning(
            "Identity Outbox Relay advisory lock was not held "
            "when release was attempted."
        )