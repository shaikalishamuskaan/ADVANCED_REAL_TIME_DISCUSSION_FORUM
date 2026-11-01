
import hashlib
import hmac
import os
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from audit.models import ActivityLog
from auth_flow.models import RecoveryCode


class RegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.payload = {
            "username": "ali_k",
            "email": "ali@example.com",
            "password": "correct-horse-battery-9",
            "display_name": "Ali Khan",
        }
    @patch("auth_flow.views.enforce_registration_limit",return_value=None,)
    @patch.dict(os.environ, {"RECOVERY_CODE_HMAC_KEY": "test-secret-key"})
    def test_registration_creates_account_and_returns_recovery_code(self,mock_rate_limit):
        response = self.client.post(
            "/api/auth/register",
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["user"]["username"], "ali_k")
        self.assertEqual(response.data["user"]["role"], "member")
        self.assertEqual(response.data["user"]["status"], "active")
        self.assertNotIn("email", response.data["user"])

        recovery_code = response.data["recovery_code"]
        self.assertRegex(
            recovery_code,
            r"^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$",
        )

        user = User.objects.get(email="ali@example.com")
        self.assertTrue(user.check_password(self.payload["password"]))
        self.assertEqual(RecoveryCode.objects.filter(user=user).count(), 1)
        self.assertEqual(ActivityLog.objects.filter(
            actor_id=user.id,
            action="account_created",
        ).count(), 1)

        stored_hash = RecoveryCode.objects.get(user=user).code_hash
        expected_hash = hmac.new(
            b"test-secret-key",
            recovery_code.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(stored_hash, expected_hash)
        self.assertNotEqual(stored_hash, recovery_code)
    @patch("auth_flow.views.enforce_registration_limit",return_value=None,)
    def test_duplicate_email_is_rejected(self,mock_rate_limit):
        first_response = self.client.post(
            "/api/auth/register",
            self.payload,
            format="json",
        )
        self.assertEqual(first_response.status_code, 201)

        duplicate_payload = {
            **self.payload,
            "username": "another_user",
        }
        response = self.client.post(
            "/api/auth/register",
            duplicate_payload,
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "email_taken")
        self.assertEqual(User.objects.count(), 1)
    @patch("auth_flow.views.enforce_registration_limit",return_value=None,)
    def test_duplicate_username_is_rejected(self,mock_rate_limit):
        first_response = self.client.post(
            "/api/auth/register",
            self.payload,
            format="json",
        )
        self.assertEqual(first_response.status_code, 201)

        duplicate_payload = {
            **self.payload,
            "email": "another@example.com",
            "username": "ALI_K",
        }
        response = self.client.post(
            "/api/auth/register",
            duplicate_payload,
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "username_taken")
        self.assertEqual(User.objects.count(), 1)

    @patch("auth_flow.views.enforce_registration_limit",return_value=None,)
    def test_invalid_username_is_rejected(self,mock_rate_limit):
        payload = {
            **self.payload,
            "username": "ab!",
        }

        response = self.client.post(
            "/api/auth/register",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)
    @patch("auth_flow.views.enforce_registration_limit",return_value=None,)
    def test_missing_display_name_is_rejected(self,mock_rate_limit):
        payload = {
            **self.payload,
            "display_name": "",
        }

        response = self.client.post(
            "/api/auth/register",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)
