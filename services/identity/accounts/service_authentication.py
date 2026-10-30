import secrets

from django.conf import settings

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ServicePrincipal:
    """
    Represents an authenticated internal service.
    """

    def __init__(self, service_name):
        self.service_name = service_name
        self.is_authenticated = True
        self.is_anonymous = False


class InternalServiceAuthentication(BaseAuthentication):
    """
    Authenticate internal services using X-Service-Key.
    """

    def authenticate(self, request):
        supplied_key = request.headers.get("X-Service-Key")

        if not supplied_key:
            return None

        matched_service = None

        for service_name, configured_key in (
            settings.SERVICE_API_KEYS.items()
        ):
            if secrets.compare_digest(
                supplied_key,
                configured_key,
            ):
                matched_service = service_name

        if matched_service is None:
            raise AuthenticationFailed(
                "Invalid service key."
            )

        principal = ServicePrincipal(matched_service)

        return principal, None

    def authenticate_header(self, request):
        return "X-Service-Key"