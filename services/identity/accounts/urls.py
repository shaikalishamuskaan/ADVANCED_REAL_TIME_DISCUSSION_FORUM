
from django.urls import path

from accounts.views import (
    CurrentUserProfileView,
    PublicUserProfileView,
    UsernameChangeView,
    PasswordChangeView,
    RecoveryCodeRegenerationView,
)

urlpatterns = [
    path("me", CurrentUserProfileView.as_view(), name="current-user"),
    path("me/username", UsernameChangeView.as_view(), name="change-username"),
    path("me/password", PasswordChangeView.as_view(), name="password-change"),
    path(
        "me/recovery-code",
        RecoveryCodeRegenerationView.as_view(),
        name="recovery-code-regeneration",
    ),
    path(
        "<str:username>",
        PublicUserProfileView.as_view(),
        name="public-user-profile",
    ),
]
