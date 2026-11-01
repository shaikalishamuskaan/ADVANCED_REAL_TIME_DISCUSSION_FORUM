
from unittest.mock import Mock

from django.test import SimpleTestCase
from rest_framework.exceptions import APIException
from rest_framework.test import APIRequestFactory


from auth_flow.rate_limits import (
    RateLimitExceeded,
    LoginRateLimitExceeded,
    RateLimitDependencyUnavailable,
    enforce_registration_limit,
    check_login_failure_limit,
    record_login_failure,
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


class LoginRateLimitTests(SimpleTestCase):
    def test_email_with_fewer_than_five_failures_is_allowed(self):
        client = Mock()
        client.get.return_value = "4"

        check_login_failure_limit("user@example.com", client=client)

        client.get.assert_called_once()

    def test_email_with_five_failures_is_blocked(self):
        client = Mock()
        client.get.return_value = "5"
        client.ttl.return_value = 120

        with self.assertRaises(LoginRateLimitExceeded) as context:
            check_login_failure_limit(
                "user@example.com",
                client=client,
            )

        self.assertEqual(context.exception.status_code, 429)
        self.assertEqual(context.exception.retry_after, 120)

    def test_email_comparison_is_case_insensitive(self):
        client = Mock()
        client.get.return_value = "5"
        client.ttl.return_value = 60

        with self.assertRaises(LoginRateLimitExceeded):
            check_login_failure_limit(
                " User@Example.com ",
                client=client,
            )

        key = client.get.call_args.args[0]
        self.assertEqual(
            key,
            "rate-limit:login:failures:"
            + __import__("hashlib").sha256(
                b"user@example.com"
            ).hexdigest(),
        )

    def test_fifth_failure_is_recorded_without_blocking_that_request(self):
        client = Mock()
        client.incr.return_value = 5

        record_login_failure("user@example.com", client=client)

        client.incr.assert_called_once()
        client.expire.assert_not_called()

    def test_redis_error_becomes_service_unavailable(self):
        import redis

        client = Mock()
        client.get.side_effect = redis.RedisError("Redis unavailable")

        with self.assertRaises(RateLimitDependencyUnavailable) as context:
            check_login_failure_limit(
                "user@example.com",
                client=client,
            )

        self.assertEqual(context.exception.status_code, 503)
