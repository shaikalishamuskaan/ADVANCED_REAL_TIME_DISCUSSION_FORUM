
from unittest.mock import Mock

from django.test import SimpleTestCase
from rest_framework.exceptions import APIException

from auth_flow.rate_limits import (
    RateLimitExceeded,
    enforce_registration_limit,
)


class RegistrationRateLimitTests(SimpleTestCase):
    def setUp(self):
        self.redis_client = Mock()
        self.redis_client.incr.return_value = 1
        self.redis_client.ttl.return_value = 3600

    def test_first_five_requests_are_allowed(self):
        for request_count in range(1, 6):
            self.redis_client.incr.return_value = request_count

            enforce_registration_limit(
                "192.0.2.10",
                client=self.redis_client,
                now=3600 * 100,
            )

        self.assertEqual(self.redis_client.incr.call_count, 5)

    def test_sixth_request_is_rejected(self):
        self.redis_client.incr.return_value = 6
        self.redis_client.ttl.return_value = 1200

        with self.assertRaises(RateLimitExceeded) as context:
            enforce_registration_limit(
                "192.0.2.10",
                client=self.redis_client,
                now=3600 * 100,
            )

        self.assertEqual(context.exception.status_code, 429)
        self.assertEqual(context.exception.retry_after, 1200)

    def test_counter_expiry_is_set_on_first_request(self):
        self.redis_client.incr.return_value = 1

        enforce_registration_limit(
            "192.0.2.10",
            client=self.redis_client,
            now=3600 * 100,
        )

        self.redis_client.expire.assert_called_once()
        self.assertEqual(
            self.redis_client.expire.call_args.args[1],
            3600,
        )
