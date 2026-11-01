from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class RelayCommandTests(SimpleTestCase):
    def invoke(self, arguments, lock_results, sleep_error=None):
        module = "audit.management.commands.run_outbox_relay"
        with patch(f"{module}.OutboxRelay") as factory, \
             patch(f"{module}.acquire_relay_lock", side_effect=lock_results) as acquire, \
             patch(f"{module}.release_relay_lock") as release, \
             patch(f"{module}.time.sleep", side_effect=sleep_error) as sleep:
            relay = factory.return_value
            relay.publish_pending_batch.side_effect = KeyboardInterrupt
            call_command("run_outbox_relay", *arguments, stdout=StringIO())
            relay.close.assert_called_once()
            return relay, acquire, release, sleep

    def test_default_mode_still_exits_when_another_relay_holds_lock(self):
        relay, acquire, release, sleep = self.invoke([], [False])
        acquire.assert_called_once()
        relay.publish_pending_batch.assert_not_called()
        release.assert_not_called()
        sleep.assert_not_called()

    def test_wait_mode_publishes_only_after_lock_is_acquired(self):
        relay, acquire, release, sleep = self.invoke(["--wait-for-lock"], [False, True])
        self.assertEqual(acquire.call_count, 2)
        sleep.assert_called_once_with(5)
        relay.publish_pending_batch.assert_called_once()
        release.assert_called_once()

    def test_interrupt_during_standby_does_not_release_another_relays_lock(self):
        relay, acquire, release, sleep = self.invoke(["--wait-for-lock"], [False], KeyboardInterrupt)
        relay.publish_pending_batch.assert_not_called()
        acquire.assert_called_once()
        release.assert_not_called()
