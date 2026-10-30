
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from audit.models import ActivityLog, Outbox
from auth_flow.models import RefreshToken


class AdminUserDisableTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="disable_admin",
            email="disable_admin@example.com",
            password="AdminPass123!",
            role=User.Role.ADMIN,
        )

        self.member = User.objects.create_user(
            username="disable_member",
            email="disable_member@example.com",
            password="MemberPass123!",
            role=User.Role.MEMBER,
        )

        self.moderator = User.objects.create_user(
            username="disable_moderator",
            email="disable_moderator@example.com",
            password="ModeratorPass123!",
            role=User.Role.MODERATOR,
        )

        self.other_admin = User.objects.create_user(
            username="disable_other_admin",
            email="disable_other_admin@example.com",
            password="OtherAdminPass123!",
            role=User.Role.ADMIN,
        )

        self.url = (
            f"/api/admin/users/{self.member.id}/disable"
        )

    def authenticate_as(self, user):
        """
        Authenticate a request as the given user.

        This uses DRF's test authentication to focus these tests
        on the admin endpoint's authorization and business logic.
        """
        self.client.force_authenticate(user=user)

    def disable_member(self, user_id=None, data=None):
        user_id = user_id or self.member.id
        data = data if data is not None else {
            "reason": "Violation of community guidelines",
        }

        return self.client.post(
            f"/api/admin/users/{user_id}/disable",
            data,
            format="json",
        )

    def create_refresh_token(self, user, revoked=False):
        token = RefreshToken.objects.create(
            user=user,
            expires_at=timezone.now() + timedelta(days=7),
            revoked_at=timezone.now() if revoked else None,
        )
        return token

    def test_admin_can_disable_member(self):
        self.authenticate_as(self.admin)

        response = self.disable_member()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.member.refresh_from_db()
        self.assertEqual(
            self.member.status,
            User.Status.DISABLED,
        )

    def test_disabling_member_revokes_unrevoked_refresh_tokens(self):
        active_token_1 = self.create_refresh_token(self.member)
        active_token_2 = self.create_refresh_token(self.member)

        previously_revoked_token = self.create_refresh_token(
            self.member,
            revoked=True,
        )

        self.authenticate_as(self.admin)
        response = self.disable_member()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        active_token_1.refresh_from_db()
        active_token_2.refresh_from_db()
        previously_revoked_token.refresh_from_db()

        self.assertIsNotNone(active_token_1.revoked_at)
        self.assertIsNotNone(active_token_2.revoked_at)
        self.assertIsNotNone(previously_revoked_token.revoked_at)

    def test_disable_creates_activity_log_and_outbox_event(self):
        self.authenticate_as(self.admin)

        response = self.disable_member()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.get(
            actor_id=self.admin.id,
            action="user_disabled",
            target_type="user",
            target_id=self.member.id,
        )
        self.assertEqual(
            log.metadata["reason"],
            "Violation of community guidelines",
        )

        event = Outbox.objects.get(
            event_type="user.disabled",
            payload__user_id=str(self.member.id),
        )
        self.assertEqual(
            event.payload["user_id"],
            str(self.member.id),
        )

    def test_non_admin_cannot_disable_member(self):
        self.authenticate_as(self.moderator)

        response = self.disable_member()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_disable_self(self):
        self.authenticate_as(self.admin)

        response = self.disable_member(user_id=self.admin.id)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_disable_another_admin(self):
        self.authenticate_as(self.admin)

        response = self.disable_member(user_id=self.other_admin.id)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.other_admin.refresh_from_db()
        self.assertEqual(
            self.other_admin.status,
            User.Status.ACTIVE,
        )

    def test_unknown_user_returns_404(self):
        import uuid

        self.authenticate_as(self.admin)

        response = self.disable_member(user_id=uuid.uuid4())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_reason_returns_400(self):
        self.authenticate_as(self.admin)

        response = self.disable_member(data={})

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_blank_reason_returns_400(self):
        self.authenticate_as(self.admin)

        response = self.disable_member(data={"reason": "   "})

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_unauthenticated_request_returns_401(self):
        response = self.disable_member()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_disabling_already_disabled_user_does_not_duplicate_records(self):
        self.member.status = User.Status.DISABLED
        self.member.save(update_fields=["status", "updated_at"])

        self.authenticate_as(self.admin)

        response = self.disable_member()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertFalse(
            ActivityLog.objects.filter(
                action="user_disabled",
                target_type="user",
                target_id=self.member.id,
            ).exists()
        )

        self.assertFalse(
            Outbox.objects.filter(
                event_type="user.disabled",
                payload__user_id=str(self.member.id),
            ).exists()
        )
