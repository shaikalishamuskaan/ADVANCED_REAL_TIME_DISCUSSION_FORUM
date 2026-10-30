from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from audit.models import Outbox


ALERT_THRESHOLD_SECONDS = 60


class Command(BaseCommand):
    help = "Check whether the oldest unpublished Outbox event exceeds 60 seconds."

    def handle(self, *args, **options):
        oldest_event = (
            Outbox.objects.filter(published_at__isnull=True)
            .order_by("created_at", "id")
            .first()
        )

        if oldest_event is None:
            self.stdout.write(
                self.style.SUCCESS("Outbox health check passed. No unpublished events.")
            )
            return

        age = timezone.now() - oldest_event.created_at
        threshold = timedelta(seconds=ALERT_THRESHOLD_SECONDS)

        if age > threshold:
            age_seconds = int(age.total_seconds())

            self.stderr.write(
                self.style.ERROR(
                    f"ALERT: Oldest unpublished Outbox event is "
                    f"{age_seconds} seconds old. "
                    f"Event ID: {oldest_event.id}"
                )
            )
            raise CommandError("Outbox publication delay exceeded 60 seconds.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Outbox health check passed. "
                f"Oldest unpublished event is {int(age.total_seconds())} seconds old."
            )
        )