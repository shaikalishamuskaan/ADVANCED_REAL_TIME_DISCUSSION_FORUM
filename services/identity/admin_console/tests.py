
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from auth_flow.tokens import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)


class AdminUserListTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com",
            username="admin_user",
            password="Secure-Admin-Password-42!",
            display_name="Admin User",
            role=User.Role.ADMIN,
        )
        self.member = User.objects.create_user(
            email="alice@example.com",
            username="alice",
            password="Secure-Test-Password-42!",
            display_name="Alice",
        )
        self.moderator = User.objects.create_user(
            email="moderator@example.com",
            username="moderator_user",
            password="Secure-Moderator-Password-42!",
            display_name="Moderator User",
            role=User.Role.MODERATOR,
        )

        self.client = APIClient()
        self.url = "/api/admin/users"

    def authenticate_as(self, user):
        refresh_token = create_refresh_token(user)
        session_id = decode_refresh_token(refresh_token)["jti"]
        access_token = create_access_token(user, session_id)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}"
        )

    def test_admin_can_list_users(self):
        self.authenticate_as(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("users", response.data)
        self.assertIn("next_cursor", response.data)
        usernames = [item["username"] for item in response.data["users"]]
        self.assertIn("alice", usernames)
        self.assertIn("admin_user", usernames)

    def test_non_admin_cannot_list_users(self):
        self.authenticate_as(self.member)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["error"]["code"],
            "insufficient_role",
        )

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_search_filters_by_username(self):
        self.authenticate_as(self.admin)

        response = self.client.get(self.url, {"query": "alice"})

        self.assertEqual(response.status_code, 200)
        usernames = [item["username"] for item in response.data["users"]]
        self.assertEqual(usernames, ["alice"])

    def test_role_filter(self):
        self.authenticate_as(self.admin)

        response = self.client.get(self.url, {"role": "moderator"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["users"])
        self.assertTrue(
            all(item["role"] == "moderator" for item in response.data["users"])
        )

    def test_status_filter(self):
        self.member.status = User.Status.DISABLED
        self.member.save(update_fields=["status"])
        self.authenticate_as(self.admin)

        response = self.client.get(self.url, {"status": "disabled"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["users"])
        self.assertTrue(
            all(item["status"] == "disabled" for item in response.data["users"])
        )

    def test_invalid_role_filter_is_rejected(self):
        self.authenticate_as(self.admin)

        response = self.client.get(self.url, {"role": "superuser"})

        self.assertEqual(response.status_code, 400)

    def test_invalid_status_filter_is_rejected(self):
        self.authenticate_as(self.admin)

        response = self.client.get(self.url, {"status": "pending"})

        self.assertEqual(response.status_code, 400)

    def test_invalid_cursor_is_rejected(self):
        self.authenticate_as(self.admin)

        response = self.client.get(
            self.url,
            {"cursor": "not-a-valid-uuid"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "invalid_cursor")
