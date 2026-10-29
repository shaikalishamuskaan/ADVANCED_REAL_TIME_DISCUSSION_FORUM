
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("auth_flow.urls")),
    path("api/users/", include("accounts.urls")),
]
