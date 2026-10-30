
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from audit.models import Outbox


class Command(BaseCommand):
    help = "Delete published Outbox events older than the retention period."

    def handle(self, *args, **options):
        retention_days = settings.OUTBOX_RETENTION_DAYS
        cutoff = timezone.now() - timedelta(days=retention_days)

        deleted_count, _ = Outbox.objects.filter(
            published_at__isnull=False,
            published_at__lt=cutoff,
        ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Outbox cleanup completed. "
                f"Deleted {deleted_count} old published record(s). "
                f"Retention period: {retention_days} day(s)."
            )
        )
