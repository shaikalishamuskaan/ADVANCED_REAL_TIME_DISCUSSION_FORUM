import uuid
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from audit.models import ActivityLog


class AdminActivityLogTests(APITestCase):

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_user",
            email="admin@example.com",
            password="TestPassword123!",
            role="admin",
        )

        self.moderator = User.objects.create_user(
            username="moderator_user",
            email="moderator@example.com",
            password="TestPassword123!",
            role="moderator",
        )

        self.member = User.objects.create_user(
            username="member_user",
            email="member@example.com",
            password="TestPassword123!",
            role="member",
        )

        self.url = "/api/admin/activity-log"

        self.log_one = ActivityLog.objects.create(
            actor_id=self.admin.id,
            action="login",
            target_type="user",
            target_id=self.admin.id,
            metadata={},
        )

        self.log_two = ActivityLog.objects.create(
            actor_id=self.member.id,
            action="password_changed",
            target_type="user",
            target_id=self.member.id,
            metadata={},
        )

        self.log_three = ActivityLog.objects.create(
            actor_id=self.admin.id,
            action="role_changed",
            target_type="user",
            target_id=self.member.id,
            metadata={},
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_admin_can_view_all_activity_records(self):
        self.authenticate(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["items"].__len__(), 3)

    def test_moderator_cannot_view_unconfirmed_actions(self):
        self.authenticate(self.moderator)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["items"], [])

    def test_moderator_sees_actual_forum_actions_from_both_privileged_roles(self):
        actions = {
            f"{action}_by_{role}"
            for action in ("thread_edited", "thread_deleted", "comment_edited",
                           "comment_deleted", "report_resolved", "report_dismissed")
            for role in ("moderator", "admin")
        } | {"comment.created", "comment.deleted", "thread_updated"}
        for action in actions:
            ActivityLog.objects.create(actor_id=self.admin.id, action=action,
                                       target_type=action.split('_')[0].split('.')[0],
                                       target_id=uuid.uuid4(), metadata={})
        self.authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["action"] for item in response.data["items"]}, actions)

    def test_actual_moderation_action_filter_returns_same_record_for_both_roles(self):
        activity = ActivityLog.objects.create(actor_id=self.moderator.id,
            action="report_resolved_by_moderator", target_type="report",
            target_id=uuid.uuid4(), metadata={})
        for user in (self.admin, self.moderator):
            with self.subTest(role=user.role):
                self.authenticate(user)
                response = self.client.get(self.url, {"action": activity.action,
                    "actor_id": str(self.moderator.id), "target_type": "report"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([item["id"] for item in response.data["items"]], [str(activity.id)])

    def test_moderator_filters_cannot_expose_account_activity(self):
        self.authenticate(self.moderator)
        for filters in ({"action": "login"}, {"action": "password_changed"},
                        {"action": "role_changed"}, {"target_type": "user"},
                        {"actor_id": str(self.admin.id)}):
            with self.subTest(filters=filters):
                response = self.client.get(self.url, filters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["items"], [])

    def test_member_cannot_view_activity_log(self):
        self.authenticate(self.member)

        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_filter_by_actor_id(self):
        self.authenticate(self.admin)

        response = self.client.get(
            self.url,
            {"actor_id": str(self.admin.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for item in response.data["items"]:
            self.assertEqual(
                str(item["actor_id"]),
                str(self.admin.id),
            )

    def test_filter_by_action(self):
        self.authenticate(self.admin)

        response = self.client.get(
            self.url,
            {"action": "login"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for item in response.data["items"]:
            self.assertEqual(item["action"], "login")

    def test_filter_by_target_type(self):
        self.authenticate(self.admin)

        response = self.client.get(
            self.url,
            {"target_type": "user"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        for item in response.data["items"]:
            self.assertEqual(item["target_type"], "user")

    def test_invalid_cursor_returns_400(self):
        self.authenticate(self.admin)

        response = self.client.get(
            self.url,
            {"cursor": "invalid-cursor"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_invalid_actor_id_returns_400(self):
        self.authenticate(self.admin)

        response = self.client.get(
            self.url,
            {"actor_id": "not-a-uuid"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
    def test_valid_cursor_returns_next_page(self):
        self.authenticate(self.admin)

        # Create enough records to exceed the default page size.
        for index in range(22):
            ActivityLog.objects.create(
                actor_id=self.admin.id,
                action=f"test_action_{index}",
                target_type="user",
                target_id=self.admin.id,
                metadata={},
            )

        first_response = self.client.get(self.url)

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        self.assertIsNotNone(first_response.data["next_cursor"])

        cursor = first_response.data["next_cursor"]

        second_response = self.client.get(
            self.url,
            {"cursor": cursor},
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_200_OK,
        )

        first_page_ids = {
            item["id"] for item in first_response.data["items"]
        }

        second_page_ids = {
            item["id"] for item in second_response.data["items"]
        }

        self.assertTrue(first_page_ids.isdisjoint(second_page_ids))
