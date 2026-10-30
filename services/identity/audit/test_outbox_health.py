from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from audit.models import Outbox


class OutboxHealthTests(TestCase):

    def test_passes_when_no_unpublished_events_exist(self):
        call_command("check_outbox_health")

    def test_passes_when_unpublished_event_is_recent(self):
        event = Outbox.objects.create(
            event_type="user.enabled",
            payload={"user_id": "test-user"},
        )

        call_command("check_outbox_health")

    def test_alerts_when_unpublished_event_is_older_than_60_seconds(self):
        event = Outbox.objects.create(
            event_type="user.disabled",
            payload={"user_id": "test-user"},
        )

        Outbox.objects.filter(id=event.id).update(
            created_at=timezone.now() - timedelta(seconds=61)
        )

        with self.assertRaises(CommandError):
            call_command("check_outbox_health")