
from datetime import timedelta
import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from audit.models import ActivityLog
from auth_flow.models import RecoveryCode
from auth_flow.services import hash_recovery_code


class AdminRecoveryCodeTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="recovery_admin",
            email="recovery_admin@example.com",
            password="AdminPass123!",
            role=User.Role.ADMIN,
        )
        self.member = User.objects.create_user(
            username="recovery_member",
            email="recovery_member@example.com",
            password="MemberPass123!",
            role=User.Role.MEMBER,
        )
        self.moderator = User.objects.create_user(
            username="recovery_moderator",
            email="recovery_moderator@example.com",
            password="ModeratorPass123!",
            role=User.Role.MODERATOR,
        )

        # Every user should already have a recovery-code row.
        RecoveryCode.objects.update_or_create(
            user=self.member,
            defaults={
                "code_hash": hash_recovery_code("OLD-CODE-1234"),
                "expires_at": None,
            },
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def issue_code(self, user_id=None):
        user_id = user_id or self.member.id
        return self.client.post(
            f"/api/admin/users/{user_id}/recovery-code",
            {},
            format="json",
        )

    def test_admin_can_issue_recovery_code(self):
        self.authenticate_as(self.admin)

        response = self.issue_code()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("recovery_code", response.data)
        self.assertIn("recovery_code_notice", response.data)
        self.assertEqual(response.data["expires_in"], 86400)

        # Verify the code format: XXXX-XXXX-XXXX-XXXX.
        self.assertRegex(
            response.data["recovery_code"],
            r"^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$",
        )

    def test_code_is_stored_as_hash_and_expires_in_24_hours(self):
        self.authenticate_as(self.admin)

        response = self.issue_code()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        plaintext_code = response.data["recovery_code"]
        stored_code = RecoveryCode.objects.get(user=self.member)

        self.assertEqual(
            stored_code.code_hash,
            hash_recovery_code(plaintext_code),
        )
        self.assertNotEqual(stored_code.code_hash, plaintext_code)

        expected_expiry = timezone.now() + timedelta(hours=24)
        self.assertAlmostEqual(
            stored_code.expires_at.timestamp(),
            expected_expiry.timestamp(),
            delta=5,
        )

    def test_new_code_replaces_previous_code(self):
        old_hash = RecoveryCode.objects.get(
            user=self.member
        ).code_hash

        self.authenticate_as(self.admin)
        response = self.issue_code()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        stored_code = RecoveryCode.objects.get(user=self.member)

        self.assertNotEqual(stored_code.code_hash, old_hash)
        self.assertEqual(
            stored_code.code_hash,
            hash_recovery_code(response.data["recovery_code"]),
        )

    def test_admin_action_is_logged(self):
        self.authenticate_as(self.admin)

        response = self.issue_code()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        log = ActivityLog.objects.get(
            actor_id=self.admin.id,
            action="admin_recovery_code_issued",
            target_type="user",
            target_id=self.member.id,
        )

        self.assertIn("expires_at", log.metadata)

    def test_non_admin_cannot_issue_recovery_code(self):
        self.authenticate_as(self.moderator)

        response = self.issue_code()

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_unknown_user_returns_404(self):
        self.authenticate_as(self.admin)

        response = self.issue_code(user_id=uuid.uuid4())

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthenticated_request_returns_401(self):
        response = self.issue_code()

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_admin_can_issue_code_for_moderator(self):
        self.authenticate_as(self.admin)

        response = self.issue_code(user_id=self.moderator.id)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            RecoveryCode.objects.filter(user=self.moderator).exists()
        )
