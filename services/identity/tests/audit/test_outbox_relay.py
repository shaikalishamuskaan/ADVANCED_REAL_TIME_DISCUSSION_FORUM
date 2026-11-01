import json
import uuid
from datetime import timedelta
from unittest.mock import Mock

import redis

from django.test import TestCase
from django.utils import timezone

from audit.models import Outbox
from audit.outbox_relay import (
    OutboxRelay,
    IDENTITY_STREAM,
    STREAM_MAX_LENGTH,
)


class OutboxRelayTests(TestCase):

    def setUp(self):
        self.relay = OutboxRelay()
        self.relay.redis_client = Mock()
        self.relay.batch_size = 100

    def create_outbox_event(self, event_type, payload, created_at=None):
        event = Outbox.objects.create(
            event_type=event_type,
            payload=payload,
        )

        if created_at is not None:
            Outbox.objects.filter(id=event.id).update(
                created_at=created_at
            )
            event.refresh_from_db()

        return event

    def test_build_envelope(self):
        event = self.create_outbox_event(
            "user.disabled",
            {"user_id": str(uuid.uuid4())},
        )

        envelope = self.relay.build_envelope(event)

        self.assertEqual(envelope["event_id"], str(event.id))
        self.assertEqual(envelope["type"], "user.disabled")
        self.assertEqual(envelope["version"], 1)
        self.assertEqual(envelope["producer"], "identity")
        self.assertEqual(envelope["payload"], event.payload)
        self.assertTrue(envelope["occurred_at"].endswith("Z"))

    def test_successful_publish_marks_event_published(self):
        event = self.create_outbox_event(
            "user.disabled",
            {"user_id": str(uuid.uuid4())},
        )

        self.relay.publish_row(event)

        event.refresh_from_db()

        self.assertIsNotNone(event.published_at)

        self.relay.redis_client.xadd.assert_called_once()

        args, kwargs = self.relay.redis_client.xadd.call_args

        self.assertEqual(args[0], IDENTITY_STREAM)
        self.assertEqual(kwargs["maxlen"], STREAM_MAX_LENGTH)
        self.assertTrue(kwargs["approximate"])

        published_envelope = json.loads(args[1]["envelope"])

        self.assertEqual(
            published_envelope["event_id"],
            str(event.id),
        )

    def test_redis_failure_does_not_mark_event_published(self):
        event = self.create_outbox_event(
            "user.disabled",
            {"user_id": str(uuid.uuid4())},
        )

        self.relay.redis_client.xadd.side_effect = redis.RedisError(
            "Redis unavailable"
        )

        with self.assertRaises(redis.RedisError):
            self.relay.publish_row(event)

        event.refresh_from_db()

        self.assertIsNone(event.published_at)

    def test_batch_processes_events_in_creation_order(self):
        now = timezone.now()

        third = self.create_outbox_event(
            "user.enabled",
            {"sequence": 3},
            now + timedelta(seconds=3),
        )

        first = self.create_outbox_event(
            "user.role_changed",
            {"sequence": 1},
            now + timedelta(seconds=1),
        )

        second = self.create_outbox_event(
            "user.disabled",
            {"sequence": 2},
            now + timedelta(seconds=2),
        )

        published_count = self.relay.publish_pending_batch()

        self.assertEqual(published_count, 3)

        published_ids = []

        for call in self.relay.redis_client.xadd.call_args_list:
            envelope = json.loads(call.args[1]["envelope"])
            published_ids.append(envelope["event_id"])

        self.assertEqual(
            published_ids,
            [str(first.id), str(second.id), str(third.id)],
        )

    def test_batch_stops_after_redis_failure(self):
        first = self.create_outbox_event(
            "user.disabled",
            {"sequence": 1},
        )

        second = self.create_outbox_event(
            "user.enabled",
            {"sequence": 2},
        )

        third = self.create_outbox_event(
            "user.role_changed",
            {"sequence": 3},
        )

        self.relay.redis_client.xadd.side_effect = [
            None,
            redis.RedisError("Redis unavailable"),
        ]

        published_count = self.relay.publish_pending_batch()

        self.assertEqual(published_count, 1)
        self.assertEqual(
            self.relay.redis_client.xadd.call_count,
            2,
        )

        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()

        self.assertIsNotNone(first.published_at)
        self.assertIsNone(second.published_at)
        self.assertIsNone(third.published_at)

    def test_already_published_events_are_not_republished(self):
        event = self.create_outbox_event(
            "user.disabled",
            {"user_id": str(uuid.uuid4())},
        )

        Outbox.objects.filter(id=event.id).update(
            published_at=timezone.now()
        )

        published_count = self.relay.publish_pending_batch()

        self.assertEqual(published_count, 0)
        self.relay.redis_client.xadd.assert_not_called()