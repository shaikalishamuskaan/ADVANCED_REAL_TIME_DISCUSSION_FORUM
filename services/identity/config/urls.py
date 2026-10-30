
from django.contrib import admin
from django.urls import include, path
from admin_console import urls as admin_urls
from accounts import internal_urls
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("auth_flow.urls")),
    path("api/users/", include("accounts.urls")),
    path("api/admin/", include(admin_urls)),
    path("internal/", include(internal_urls)),
]
