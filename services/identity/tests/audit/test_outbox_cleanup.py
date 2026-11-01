
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from audit.models import Outbox


class OutboxCleanupTests(TestCase):

    def test_deletes_old_published_events(self):
        old_time = timezone.now() - timedelta(
            days=settings.OUTBOX_RETENTION_DAYS + 1
        )

        event = Outbox.objects.create(
            event_type="user.disabled",
            payload={"user_id": "test-user"},
            published_at=old_time,
        )

        call_command("cleanup_outbox")

        self.assertFalse(
            Outbox.objects.filter(id=event.id).exists()
        )

    def test_keeps_recent_published_events(self):
        recent_time = timezone.now() - timedelta(days=2)

        event = Outbox.objects.create(
            event_type="user.enabled",
            payload={"user_id": "test-user"},
            published_at=recent_time,
        )

        call_command("cleanup_outbox")

        self.assertTrue(
            Outbox.objects.filter(id=event.id).exists()
        )

    def test_keeps_old_unpublished_events(self):
        old_time = timezone.now() - timedelta(
            days=settings.OUTBOX_RETENTION_DAYS + 1
        )

        event = Outbox.objects.create(
            event_type="user.role_changed",
            payload={"user_id": "test-user"},
            published_at=None,
        )

        # The event is old by creation time but remains unpublished.
        Outbox.objects.filter(id=event.id).update(
            created_at=old_time
        )

        call_command("cleanup_outbox")

        self.assertTrue(
            Outbox.objects.filter(id=event.id).exists()
        )
