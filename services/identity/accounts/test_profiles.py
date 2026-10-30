
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from auth_flow.tokens import create_access_token, create_refresh_token, decode_refresh_token


class ProfileAPITests(TestCase):
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
        self.access_token = create_access_token(self.user, session_id)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access_token}"
        )

    def test_get_current_profile(self):
        response = self.client.get("/api/users/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["username"], "alice")
        self.assertEqual(response.data["user"]["display_name"], "Alice")
        self.assertNotIn("email", response.data["user"])
        self.assertNotIn("password", response.data["user"])
        self.assertNotIn("password_hash", response.data["user"])

    def test_current_profile_requires_authentication(self):
        self.client.credentials()

        response = self.client.get("/api/users/me")

        self.assertEqual(response.status_code, 401)

    def test_invalid_access_token_is_rejected(self):
        self.client.credentials(
            HTTP_AUTHORIZATION="Bearer invalid-token"
        )

        response = self.client.get("/api/users/me")

        self.assertEqual(response.status_code, 401)

    def test_patch_current_profile(self):
        response = self.client.patch(
            "/api/users/me",
            {
                "display_name": "Alice Updated",
                "bio": "Learning backend development.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["user"]["display_name"],
            "Alice Updated",
        )
        self.assertEqual(
            response.data["user"]["bio"],
            "Learning backend development.",
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "Alice Updated")

    def test_patch_rejects_empty_display_name(self):
        response = self.client.patch(
            "/api/users/me",
            {"display_name": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_patch_cannot_change_role(self):
        response = self.client.patch(
            "/api/users/me",
            {"role": "admin"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, "member")

    def test_public_profile_does_not_expose_email(self):
        self.client.credentials()

        response = self.client.get("/api/users/alice")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["username"], "alice")
        self.assertNotIn("email", response.data["user"])
        self.assertNotIn("password", response.data["user"])

    def test_unknown_public_profile_returns_404(self):
        self.client.credentials()

        response = self.client.get("/api/users/unknown_user")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "not_found")
