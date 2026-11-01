import uuid

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User


TEST_KEYS = {
    "discussion": "test-discussion-secret",
    "notify": "test-notify-secret",
    "realtime": "test-realtime-secret",
}


@override_settings(SERVICE_API_KEYS=TEST_KEYS)
class InternalIdentityAPITests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="ali@example.com",
            username="ali_k",
            password="TestPassword123!",
            display_name="Ali Khan",
        )

    def authenticate_service(self, service):
        self.client.credentials(
            HTTP_X_SERVICE_KEY=TEST_KEYS[service]
        )

    def test_status_lookup_by_discussion_service(self):
        self.authenticate_service("discussion")

        response = self.client.get(
            f"/internal/users/{self.user.id}/status"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "ali_k")
        self.assertEqual(response.data["role"], "member")
        self.assertEqual(response.data["status"], "active")

    def test_status_lookup_by_notify_service(self):
        self.authenticate_service("notify")

        response = self.client.get(
            f"/internal/users/{self.user.id}/status"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_status_lookup_by_realtime_service(self):
        self.authenticate_service("realtime")

        response = self.client.get(
            f"/internal/users/{self.user.id}/status"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_status_lookup_for_unknown_user_returns_404(self):
        self.authenticate_service("discussion")

        response = self.client.get(
            f"/internal/users/{uuid.uuid4()}/status"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_missing_service_key_returns_401(self):
        response = self.client.get(
            f"/internal/users/{self.user.id}/status"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_invalid_service_key_returns_401(self):
        self.client.credentials(
            HTTP_X_SERVICE_KEY="invalid-secret"
        )

        response = self.client.get(
            f"/internal/users/{self.user.id}/status"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_realtime_cannot_access_batch_endpoint(self):
        self.authenticate_service("realtime")

        response = self.client.post(
            "/internal/users/batch",
            {"ids": [str(self.user.id)]},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_discussion_can_access_batch_endpoint(self):
        self.authenticate_service("discussion")

        response = self.client.post(
            "/internal/users/batch",
            {"ids": [str(self.user.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 1)

        item = response.data["items"][0]

        self.assertEqual(item["username"], "ali_k")
        self.assertEqual(item["display_name"], "Ali Khan")
        self.assertIn("avatar_url", item)

        self.assertNotIn("email", item)
        self.assertNotIn("password", item)

    def test_batch_endpoint_ignores_unknown_user_ids(self):
        self.authenticate_service("discussion")

        response = self.client.post(
            "/internal/users/batch",
            {
                "ids": [
                    str(self.user.id),
                    str(uuid.uuid4()),
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 1)

    def test_notify_can_resolve_usernames_case_insensitively(self):
        self.authenticate_service("notify")

        response = self.client.post(
            "/internal/users/resolve",
            {"usernames": ["ALI_K"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(
            response.data["items"][0]["username"],
            "ali_k",
        )

    def test_discussion_cannot_access_username_resolution(self):
        self.authenticate_service("discussion")

        response = self.client.post(
            "/internal/users/resolve",
            {"usernames": ["ali_k"]},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_invalid_batch_request_returns_400(self):
        self.authenticate_service("discussion")

        response = self.client.post(
            "/internal/users/batch",
            {"ids": ["not-a-uuid"]},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_invalid_username_resolution_request_returns_400(self):
        self.authenticate_service("notify")

        response = self.client.post(
            "/internal/users/resolve",
            {"usernames": []},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )