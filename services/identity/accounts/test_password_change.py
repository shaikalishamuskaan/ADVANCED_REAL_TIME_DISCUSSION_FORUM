
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from auth_flow.models import RefreshToken
from auth_flow.tokens import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="alice@example.com",
            username="alice",
            password="Secure-Test-Password-42!",
            display_name="Alice",
        )
        self.client = APIClient()

        self.refresh_token = create_refresh_token(self.user)
        self.session_id = decode_refresh_token(self.refresh_token)["jti"]
        access_token = create_access_token(self.user, self.session_id)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}"
        )
        self.url = "/api/users/me/password"

    @patch("accounts.views.enforce_password_change_limit")
    def test_password_changes_and_preserves_current_session(
        self, mock_rate_limit
    ):
        other_refresh_token = create_refresh_token(self.user)
        other_session_id = decode_refresh_token(other_refresh_token)["jti"]

        response = self.client.post(
            self.url,
            {
                "current_password": "Secure-Test-Password-42!",
                "new_password": "New-Secure-Password-57!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password("New-Secure-Password-57!")
        )

        self.assertTrue(
            RefreshToken.objects.filter(
                jti=self.session_id,
                revoked_at__isnull=True,
            ).exists()
        )
        self.assertTrue(
            RefreshToken.objects.filter(
                jti=other_session_id,
                revoked_at__isnull=False,
            ).exists()
        )

    @patch("accounts.views.enforce_password_change_limit")
    def test_wrong_current_password_is_rejected(self, mock_rate_limit):
        response = self.client.post(
            self.url,
            {
                "current_password": "Wrong-Password-42!",
                "new_password": "New-Secure-Password-57!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_request_is_rejected(self):
        self.client.credentials()

        response = self.client.post(
            self.url,
            {
                "current_password": "Secure-Test-Password-42!",
                "new_password": "New-Secure-Password-57!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 401)
