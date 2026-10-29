
from django.urls import path

from accounts.views import (
    CurrentUserProfileView,
    PublicUserProfileView,
)

urlpatterns = [
    path("me", CurrentUserProfileView.as_view(), name="current-user"),
    path(
        "<str:username>",
        PublicUserProfileView.as_view(),
        name="public-user-profile",
    ),
]
