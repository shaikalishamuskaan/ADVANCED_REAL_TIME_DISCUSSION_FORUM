from django.urls import path

from admin_console.views import (
    AdminUserListView,
    AdminUserRoleChangeView,
    AdminUserDisableView,
    AdminUserEnableView,
    AdminUserRecoveryCodeView,
    AdminActivityLogView,
)

urlpatterns = [
    path("users", AdminUserListView.as_view(), name="admin-user-list"),
    path(
        "users/<uuid:user_id>/role",
        AdminUserRoleChangeView.as_view(),
        name="admin-user-role-change",

    ),
    path(
    "users/<uuid:user_id>/disable",
    AdminUserDisableView.as_view(),
    name="admin-user-disable",
),

path(
    "users/<uuid:user_id>/enable",
    AdminUserEnableView.as_view(),
    name="admin-user-enable",
),

path(
    "users/<uuid:user_id>/recovery-code",
    AdminUserRecoveryCodeView.as_view(),
    name="admin-user-recovery-code",
),
path(
    "activity-log",
    AdminActivityLogView.as_view(),
    name="admin-activity-log",
),
]