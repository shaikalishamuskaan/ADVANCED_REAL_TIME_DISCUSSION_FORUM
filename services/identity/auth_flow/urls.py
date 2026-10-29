
from django.urls import path

from auth_flow.views import RegisterView

urlpatterns = [
    path("register", RegisterView.as_view(), name="register"),
]
