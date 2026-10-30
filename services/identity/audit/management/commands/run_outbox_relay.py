import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connections

from audit.outbox_relay import (
    OutboxRelay,
    acquire_relay_lock,
    release_relay_lock,
)


logger = logging.getLogger(__name__)

INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 30


class Command(BaseCommand):
    help = "Run the Identity transactional Outbox Relay."

    def handle(self, *args, **options):
        relay = OutboxRelay()
        lock_acquired = False
        backoff_seconds = INITIAL_BACKOFF_SECONDS

        self.stdout.write(
            self.style.SUCCESS(
                "Starting Identity Outbox Relay..."
            )
        )

        try:
            lock_acquired = acquire_relay_lock()

            if not lock_acquired:
                self.stdout.write(
                    self.style.WARNING(
                        "Another Identity Outbox Relay is already running. "
                        "Exiting."
                    )
                )
                return

            self.stdout.write(
                self.style.SUCCESS(
                    "Identity Outbox Relay acquired the advisory lock."
                )
            )

            while True:
                try:
                    published_count = relay.publish_pending_batch()

                    if published_count:
                        self.stdout.write(
                            f"Published {published_count} Outbox event(s)."
                        )

                    if relay.last_batch_failed:
                        logger.warning(
                            "Redis failure detected. "
                            "Retrying in %s second(s).",
                            backoff_seconds,
                        )

                        time.sleep(backoff_seconds)

                        backoff_seconds = min(
                            backoff_seconds * 2,
                            MAX_BACKOFF_SECONDS,
                        )
                    else:
                        backoff_seconds = INITIAL_BACKOFF_SECONDS

                        time.sleep(
                            settings.OUTBOX_RELAY_INTERVAL_MS / 1000
                        )

                except Exception:
                    logger.exception(
                        "Unexpected error while processing the Outbox batch."
                    )

                    time.sleep(backoff_seconds)

                    backoff_seconds = min(
                        backoff_seconds * 2,
                        MAX_BACKOFF_SECONDS,
                    )

        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING(
                    "Stopping Identity Outbox Relay..."
                )
            )

        finally:
            relay.close()

            if lock_acquired:
                try:
                    release_relay_lock()
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Identity Outbox Relay lock released."
                        )
                    )
                except Exception:
                    logger.exception(
                        "Failed to release the Identity Outbox Relay lock."
                    )