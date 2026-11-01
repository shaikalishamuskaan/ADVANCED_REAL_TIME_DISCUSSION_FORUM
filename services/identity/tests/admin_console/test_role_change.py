from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from auth_flow.tokens import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from audit.models import ActivityLog, Outbox


class AdminUserRoleChangeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="roleadmin@example.com",
            username="roleadmin",
            password="Secure-Admin-Password-42!",
            display_name="Role Admin",
            role=User.Role.ADMIN,
        )
        self.member = User.objects.create_user(
            email="rolemember@example.com",
            username="rolemember",
            password="Secure-Member-Password-42!",
            display_name="Role Member",
        )
        self.client = APIClient()

    def authenticate_as(self, user):
        refresh = create_refresh_token(user)
        session_id = decode_refresh_token(refresh)["jti"]
        access = create_access_token(user, session_id)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access}"
        )

    def role_url(self, user):
        return f"/api/admin/users/{user.id}/role"

    def test_admin_can_change_role_and_records_event(self):
        self.authenticate_as(self.admin)

        response = self.client.patch(
            self.role_url(self.member),
            {"role": "moderator"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.member.refresh_from_db()
        self.assertEqual(self.member.role, User.Role.MODERATOR)

        log = ActivityLog.objects.get(
            action="role_changed",
            target_id=self.member.id,
        )
        self.assertEqual(log.actor_id, self.admin.id)
        self.assertEqual(log.metadata["old_role"], "member")
        self.assertEqual(log.metadata["new_role"], "moderator")

        event = Outbox.objects.get(event_type="user.role_changed")
        self.assertEqual(event.payload["user_id"], str(self.member.id))
        self.assertEqual(event.payload["old_role"], "member")
        self.assertEqual(event.payload["new_role"], "moderator")

    def test_non_admin_cannot_change_role(self):
        self.authenticate_as(self.member)

        response = self.client.patch(
            self.role_url(self.admin),
            {"role": "moderator"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_change_own_role(self):
        self.authenticate_as(self.admin)

        response = self.client.patch(
            self.role_url(self.admin),
            {"role": "member"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_invalid_role_is_rejected(self):
        self.authenticate_as(self.admin)

        response = self.client.patch(
            self.role_url(self.member),
            {"role": "superuser"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_missing_user_is_rejected(self):
        import uuid

        self.authenticate_as(self.admin)

        response = self.client.patch(
            f"/api/admin/users/{uuid.uuid4()}/role",
            {"role": "moderator"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.patch(
            self.role_url(self.member),
            {"role": "moderator"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)