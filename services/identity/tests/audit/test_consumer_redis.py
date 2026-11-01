import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from audit.management.commands.consume_events import (
    AuditEventConsumer,
    CONSUMER_GROUP,
    CONSUMER_NAME,
    DISCUSSION_STREAM,
)


class AuditEventConsumerRedisTests(SimpleTestCase):

    def setUp(self):
        self.consumer = AuditEventConsumer()
        self.consumer.redis_client = Mock()

        self.envelope = {
            "event_id": "e130a780-9d83-46b1-a88c-023e3d5057b5",
            "type": "activity.recorded",
            "version": 1,
            "occurred_at": "2026-10-30T10:00:00Z",
            "producer": "discussion",
            "payload": {
                "actor_id": "11111111-1111-1111-1111-111111111111",
                "actor_role": "moderator",
                "action": "comment.deleted",
                "target_type": "comment",
                "target_id": "22222222-2222-2222-2222-222222222222",
                "metadata": {},
                "occurred_at": "2026-10-30T10:00:00Z",
            },
        }

        self.fields = {
            "envelope": __import__("json").dumps(self.envelope)
        }

    def test_consumer_group_is_created(self):
        self.consumer.ensure_consumer_group()

        self.consumer.redis_client.xgroup_create.assert_called_once_with(
            name=DISCUSSION_STREAM,
            groupname=CONSUMER_GROUP,
            id="0-0",
            mkstream=True,
        )

    def test_existing_consumer_group_is_accepted(self):
        self.consumer.redis_client.xgroup_create.side_effect = (
            __import__("redis").ResponseError("BUSYGROUP Consumer Group name already exists")
        )

        self.consumer.ensure_consumer_group()

        self.consumer.redis_client.xgroup_create.assert_called_once()

    @patch(
        "audit.management.commands.consume_events.process_event"
    )
    def test_valid_message_is_processed_before_acknowledgement(
        self, mock_process_event
    ):
        calls = []

        def record_processing(envelope):
            calls.append("processed")

        def record_acknowledgement(*args):
            calls.append("acknowledged")

        mock_process_event.side_effect = record_processing
        self.consumer.redis_client.xack.side_effect = record_acknowledgement

        self.consumer.handle_message("123-0", self.fields)

        self.assertEqual(
            calls,
            ["processed", "acknowledged"],
        )

        mock_process_event.assert_called_once_with(self.envelope)

        self.consumer.redis_client.xack.assert_called_once_with(
            DISCUSSION_STREAM,
            CONSUMER_GROUP,
            "123-0",
        )

    @patch(
        "audit.management.commands.consume_events.process_event"
    )
    def test_failed_processing_does_not_acknowledge_message(
        self, mock_process_event
    ):
        mock_process_event.side_effect = RuntimeError(
            "Database unavailable"
        )

        with self.assertRaises(RuntimeError):
            self.consumer.handle_message("123-0", self.fields)

        self.consumer.redis_client.xack.assert_not_called()

    def test_pending_messages_are_reclaimed(self):
        self.consumer.redis_client.xautoclaim.return_value = (
            "0-0",
            [("123-0", self.fields)],
            [],
        )

        with patch.object(
            self.consumer,
            "handle_message",
        ) as mock_handle:
            count = self.consumer.reclaim_pending_messages()

        self.assertEqual(count, 1)

        self.consumer.redis_client.xautoclaim.assert_called_once_with(
            name=DISCUSSION_STREAM,
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            min_idle_time=60_000,
            start_id="0-0",
            count=10,
        )

        mock_handle.assert_called_once_with(
            "123-0",
            self.fields,
        )

    def test_no_pending_messages_returns_zero(self):
        self.consumer.redis_client.xautoclaim.return_value = (
            "0-0",
            [],
            [],
        )

        count = self.consumer.reclaim_pending_messages()

        self.assertEqual(count, 0)

    @patch("audit.management.commands.consume_events.process_event")
    def test_known_non_audit_events_are_acknowledged_without_database_processing(self, process):
        from audit.management.commands.consume_events import IGNORED_EVENT_TYPES
        for event_type in IGNORED_EVENT_TYPES:
            with self.subTest(event_type=event_type):
                self.consumer.redis_client.reset_mock()
                envelope = dict(self.envelope, type=event_type)
                self.consumer.handle_message("123-0", {"envelope": json.dumps(envelope)})
                self.consumer.redis_client.xack.assert_called_once_with(DISCUSSION_STREAM, CONSUMER_GROUP, "123-0")
        process.assert_not_called()

    def test_malformed_and_unknown_events_remain_pending(self):
        invalid = [[], dict(self.envelope, event_id="invalid"),
                   dict(self.envelope, version=2), dict(self.envelope, producer="unknown"),
                   dict(self.envelope, occurred_at="invalid"), dict(self.envelope, payload=[]),
                   dict(self.envelope, type="unknown")]
        for envelope in invalid:
            with self.subTest(envelope=envelope):
                self.consumer.redis_client.reset_mock()
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    self.consumer.handle_message("123-0", {"envelope": json.dumps(envelope)})
                self.consumer.redis_client.xack.assert_not_called()

    @patch("audit.management.commands.consume_events.process_event")
    def test_reclaimed_thread_event_does_not_block_following_audit_event(self, process):
        self.consumer.redis_client.xautoclaim.return_value = ("0-0", [
            ("123-0", {"envelope": json.dumps(dict(self.envelope, type="thread.created"))}),
            ("124-0", self.fields),
        ], [])
        self.assertEqual(self.consumer.reclaim_pending_messages(), 2)
        process.assert_called_once_with(self.envelope)
        self.assertEqual(self.consumer.redis_client.xack.call_count, 2)
