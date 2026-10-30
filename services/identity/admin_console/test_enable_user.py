
import uuid

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from audit.models import ActivityLog, Outbox


class AdminUserEnableTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="enable_admin",
            email="enable_admin@example.com",
            password="AdminPass123!",
            role=User.Role.ADMIN,
        )

        self.member = User.objects.create_user(
            username="enable_member",
            email="enable_member@example.com",
            password="MemberPass123!",
            role=User.Role.MEMBER,
        )

        self.moderator = User.objects.create_user(
            username="enable_moderator",
            email="enable_moderator@example.com",
            password="ModeratorPass123!",
            role=User.Role.MODERATOR,
        )

        self.other_admin = User.objects.create_user(
            username="enable_other_admin",
            email="enable_other_admin@example.com",
            password="OtherAdminPass123!",
            role=User.Role.ADMIN,
        )

        # Start with a disabled member.
        self.member.status = User.Status.DISABLED
        self.member.save(update_fields=["status", "updated_at"])

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def enable_user(self, user_id=None):
        user_id = user_id or self.member.id

        return self.client.post(
            f"/api/admin/users/{user_id}/enable",
            {},
            format="json",
        )

    def test_admin_can_enable_disabled_member(self):
        self.authenticate_as(self.admin)

        response = self.enable_user()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.member.refresh_from_db()
        self.assertEqual(self.member.status, User.Status.ACTIVE)

    def test_enable_creates_activity_log_and_outbox_event(self):
        self.authenticate_as(self.admin)

        response = self.enable_user()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue(
            ActivityLog.objects.filter(
                actor_id=self.admin.id,
                action="user_enabled",
                target_type="user",
                target_id=self.member.id,
            ).exists()
        )

        event = Outbox.objects.get(
            event_type="user.enabled",
            payload__user_id=str(self.member.id),
        )
        self.assertEqual(
            event.payload["user_id"],
            str(self.member.id),
        )

    def test_non_admin_cannot_enable_user(self):
        self.authenticate_as(self.moderator)

        response = self.enable_user()

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.member.refresh_from_db()
        self.assertEqual(self.member.status, User.Status.DISABLED)

    def test_admin_cannot_enable_self(self):
        self.authenticate_as(self.admin)

        response = self.enable_user(user_id=self.admin.id)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_cannot_enable_another_admin(self):
        self.authenticate_as(self.admin)

        response = self.enable_user(user_id=self.other_admin.id)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_unknown_user_returns_404(self):
        self.authenticate_as(self.admin)

        response = self.enable_user(user_id=uuid.uuid4())

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_request_returns_401(self):
        response = self.enable_user()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_enabling_already_active_user_does_not_duplicate_records(self):
        self.member.status = User.Status.ACTIVE
        self.member.save(update_fields=["status", "updated_at"])

        self.authenticate_as(self.admin)

        response = self.enable_user()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertFalse(
            ActivityLog.objects.filter(
                action="user_enabled",
                target_type="user",
                target_id=self.member.id,
            ).exists()
        )

        self.assertFalse(
            Outbox.objects.filter(
                event_type="user.enabled",
                payload__user_id=str(self.member.id),
            ).exists()
        )
