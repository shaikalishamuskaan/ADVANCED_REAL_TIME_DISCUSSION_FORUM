from django.urls import path

from accounts.internal_views import (
    InternalUserStatusView,
    InternalUserBatchView,
    InternalUsernameResolveView,
)

urlpatterns = [
    path(
        "users/<uuid:user_id>/status",
        InternalUserStatusView.as_view(),
        name="internal-user-status",
    ),
    path(
        "users/batch",
        InternalUserBatchView.as_view(),
        name="internal-user-batch",
    ),
    path(
        "users/resolve",
        InternalUsernameResolveView.as_view(),
        name="internal-user-resolve",
    ),
]