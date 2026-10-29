
from django.urls import path

from auth_flow.views import RegisterView,LoginView,RefreshView,LogoutView,PasswordResetView

urlpatterns = [
    path("register", RegisterView.as_view(), name="register"),
    path("login", LoginView.as_view(), name="login"),
    path("refresh", RefreshView.as_view(), name="refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("password/reset", PasswordResetView.as_view(), name="password-reset"),
]
