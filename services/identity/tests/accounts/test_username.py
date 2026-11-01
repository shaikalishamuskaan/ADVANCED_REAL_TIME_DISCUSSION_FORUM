from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from auth_flow.tokens import create_access_token, create_refresh_token, decode_refresh_token
from audit.models import ActivityLog


class UsernameChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="alice@example.com",
            username="alice",
            password="Secure-Test-Password-42!",
            display_name="Alice",
        )
        self.client = APIClient()
        refresh_token = create_refresh_token(self.user)
        session_id = decode_refresh_token(refresh_token)["jti"]
        token = create_access_token(self.user, session_id)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        self.url = "/api/users/me/username"

    def test_username_changes_successfully(self):
        response = self.client.post(
            self.url,
            {"username": "alice_new"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice_new")
        self.assertEqual(self.user.username_normalized, "alice_new")
        self.assertTrue(
            ActivityLog.objects.filter(
                actor_id=self.user.id,
                action="username_changed",
            ).exists()
        )

    def test_duplicate_username_is_rejected(self):
        User.objects.create_user(
            email="bob@example.com",
            username="bob",
            password="Secure-Test-Password-42!",
            display_name="Bob",
        )

        response = self.client.post(
            self.url,
            {"username": "BOB"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_username_is_rejected(self):
        response = self.client.post(
            self.url,
            {"username": "ab"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_change_within_30_days_is_rejected(self):
        ActivityLog.objects.create(
            actor_id=self.user.id,
            action="username_changed",
            target_type="user",
            target_id=self.user.id,
            metadata={
                "old_username": "alice_old",
                "new_username": "alice",
            },
        )

        response = self.client.post(
            self.url,
            {"username": "alice_new"},
            format="json",
        )

        self.assertEqual(response.status_code, 429)

    def test_unauthenticated_request_is_rejected(self):
        self.client.credentials()

        response = self.client.post(
            self.url,
            {"username": "alice_new"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)