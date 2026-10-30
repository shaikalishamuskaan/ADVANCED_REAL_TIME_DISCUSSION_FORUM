import uuid
from unittest.mock import patch

from django.test import TestCase

from audit.models import ActivityLog, ProcessedEvent
from audit.management.commands.consume_events import (
    CONSUMER_KEY,
    process_event,
)


class ProcessEventTests(TestCase):
    def setUp(self):
        self.event_id = uuid.uuid4()
        self.actor_id = uuid.uuid4()
        self.target_id = uuid.uuid4()

        self.envelope = {
            "event_id": str(self.event_id),
            "type": "activity.recorded",
            "version": 1,
            "occurred_at": "2026-10-30T10:00:00Z",
            "producer": "discussion",
            "payload": {
                "actor_id": str(self.actor_id),
                "actor_role": "moderator",
                "action": "comment.deleted",
                "target_type": "comment",
                "target_id": str(self.target_id),
                "metadata": {
                    "reason": "policy_violation"
                },
                "occurred_at": "2026-10-30T10:00:00Z",
            },
        }

    def test_valid_event_creates_activity_log_and_processed_event(self):
        result = process_event(self.envelope)

        self.assertTrue(result)

        self.assertEqual(ActivityLog.objects.count(), 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)

        activity = ActivityLog.objects.get()

        self.assertEqual(activity.actor_id, self.actor_id)
        self.assertEqual(activity.action, "comment.deleted")
        self.assertEqual(activity.target_type, "comment")
        self.assertEqual(activity.target_id, self.target_id)

        self.assertEqual(
            activity.metadata,
            {
                "reason": "policy_violation",
                "actor_role": "moderator",
            },
        )

        processed = ProcessedEvent.objects.get()

        self.assertEqual(processed.event_id, self.event_id)
        self.assertEqual(processed.consumer, CONSUMER_KEY)

    def test_duplicate_event_is_not_processed_twice(self):
        first_result = process_event(self.envelope)
        second_result = process_event(self.envelope)

        self.assertTrue(first_result)
        self.assertFalse(second_result)

        self.assertEqual(ActivityLog.objects.count(), 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)

    def test_activity_log_failure_rolls_back_processed_event(self):
        with patch(
            "audit.management.commands.consume_events.ActivityLog.objects.create",
            side_effect=RuntimeError("Simulated database failure"),
        ):
            with self.assertRaises(RuntimeError):
                process_event(self.envelope)

        self.assertEqual(ActivityLog.objects.count(), 0)
        self.assertEqual(ProcessedEvent.objects.count(), 0)

    def test_unsupported_event_type_is_rejected(self):
        invalid_envelope = self.envelope.copy()
        invalid_envelope["type"] = "user.disabled"

        with self.assertRaises(ValueError):
            process_event(invalid_envelope)

        self.assertEqual(ActivityLog.objects.count(), 0)
        self.assertEqual(ProcessedEvent.objects.count(), 0)