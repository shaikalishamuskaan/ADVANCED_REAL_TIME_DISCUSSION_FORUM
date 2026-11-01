
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from auth_flow.services import AccountDisabled, InvalidCredentials


class LoginAPITests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/auth/login"
        self.payload = {
            "email": "ali@example.com",
            "password": "correct-horse-battery-9",
        }

    @patch("auth_flow.views.create_login_tokens")
    @patch("auth_flow.views.clear_login_failures")
    @patch("auth_flow.views.authenticate_user")
    @patch("auth_flow.views.check_login_failure_limit")
    @patch("auth_flow.views.enforce_login_ip_limit")
    def test_successful_login_returns_access_token_and_cookie(
        self,
        mock_ip_limit,
        mock_email_limit,
        mock_authenticate,
        mock_clear_failures,
        mock_create_tokens,
    ):
        mock_authenticate.return_value = object()
        mock_create_tokens.return_value = ("test-access-token", "test-refresh-token")

        response = self.client.post(
            self.url,
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["access_token"], "test-access-token")
        self.assertEqual(response.data["token_type"], "Bearer")
        self.assertEqual(response.data["expires_in"], 900)

        cookie = response.cookies["refresh_token"]
        self.assertEqual(cookie.value, "test-refresh-token")
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/api/auth")

        mock_clear_failures.assert_called_once_with("ali@example.com")
        mock_create_tokens.assert_called_once()

    @patch("auth_flow.views.authenticate_user", return_value=None)
    @patch("auth_flow.views.record_login_failure")
    @patch("auth_flow.views.check_login_failure_limit")
    @patch("auth_flow.views.enforce_login_ip_limit")
    def test_invalid_credentials_return_401(
        self,
        mock_ip_limit,
        mock_email_limit,
        mock_record_failure,
        mock_authenticate,
    ):
        response = self.client.post(
            self.url,
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.data["error"]["code"],
            "invalid_credentials",
        )
        mock_record_failure.assert_called_once_with("ali@example.com")

    @patch(
        "auth_flow.views.authenticate_user",
        side_effect=AccountDisabled(),
    )
    @patch("auth_flow.views.check_login_failure_limit")
    @patch("auth_flow.views.enforce_login_ip_limit")
    def test_disabled_account_returns_403(
        self,
        mock_ip_limit,
        mock_email_limit,
        mock_authenticate,
    ):
        response = self.client.post(
            self.url,
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.data["error"]["code"],
            "account_disabled",
        )

    @patch(
        "auth_flow.views.enforce_login_ip_limit",
        side_effect=Exception("Unexpected failure"),
    )
    def test_unexpected_rate_limit_error_is_not_silently_ignored(
        self,
        mock_ip_limit,
    ):
        with self.assertRaises(Exception):
            self.client.post(
                self.url,
                self.payload,
                format="json",
            )

class RefreshEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/auth/refresh"
        self.client.cookies["refresh_token"] = "test-refresh-token"
        self.client.credentials(
            HTTP_ORIGIN="http://localhost:5173"
        )

    @patch("auth_flow.views.rotate_refresh_token")
    def test_successful_refresh_returns_new_tokens(self, mock_rotate):
        mock_rotate.return_value = (
            "new-access-token",
            "new-refresh-token",
        )

        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["access_token"],
            "new-access-token",
        )
        self.assertEqual(response.data["token_type"], "Bearer")

        cookie = response.cookies["refresh_token"]
        self.assertEqual(cookie.value, "new-refresh-token")
        self.assertTrue(cookie["httponly"])
        self.assertTrue(cookie["secure"])
        self.assertEqual(cookie["samesite"], "Strict")

    @patch("auth_flow.views.rotate_refresh_token")
    def test_invalid_refresh_token_returns_401(self, mock_rotate):
        mock_rotate.side_effect = InvalidCredentials()

        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.data["error"]["code"],
            "invalid_credentials",
        )

    def test_missing_refresh_cookie_returns_401(self):
        self.client.cookies.clear()

        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, 401)

    def test_disallowed_origin_returns_403(self):
        request = APIClient()
        request.cookies["refresh_token"] = "test-refresh-token"
        request.credentials(HTTP_ORIGIN="https://attacker.example")

        response = request.post(self.url, format="json")

        self.assertEqual(response.status_code, 403)

class LogoutEndpointTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/auth/logout"

    @patch("auth_flow.views.revoke_refresh_token")
    def test_logout_revokes_token_and_clears_cookie(self, mock_revoke):
        self.client.cookies["refresh_token"] = "test-refresh-token"

        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, 204)
        mock_revoke.assert_called_once_with("test-refresh-token")
        self.assertEqual(
            response.cookies["refresh_token"]["max-age"],
            0,
        )

    @patch("auth_flow.views.revoke_refresh_token")
    def test_logout_without_cookie_still_succeeds(self, mock_revoke):
        response = self.client.post(self.url, format="json")

        self.assertEqual(response.status_code, 204)
        mock_revoke.assert_not_called()
