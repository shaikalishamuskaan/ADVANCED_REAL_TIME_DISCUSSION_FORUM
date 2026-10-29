
import jwt

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import (
    BaseAuthentication,
    get_authorization_header,
)
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from config.settings import load_jwt_key

class RS256AccessTokenAuthentication(BaseAuthentication):
    """Authenticate requests using RS256 access tokens."""

    def authenticate(self, request):
        auth_header = get_authorization_header(request).split()

        # No Authorization header: let DRF's permission checks handle it.
        if not auth_header:
            return None

        if auth_header[0].lower() != b"bearer":
            return None

        if len(auth_header) != 2:
            raise AuthenticationFailed("Invalid authorization header.")

        try:
            token = auth_header[1].decode("utf-8")
            public_key = load_jwt_key(settings.JWT_PUBLIC_KEY_PATH)

            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                issuer=settings.JWT_ISSUER,
                audience=settings.JWT_AUDIENCE,
                options={
                    "require": [
                        "sub",
                        "iss",
                        "aud",
                        "iat",
                        "exp",
                    ]
                },
            )
        except (jwt.PyJWTError, UnicodeDecodeError, ValueError):
            raise AuthenticationFailed(
                "Invalid or expired access token."
            )

        User = get_user_model()

        try:
            user = User.objects.get(pk=payload["sub"])
        except (User.DoesNotExist, ValueError, TypeError, KeyError):
            raise AuthenticationFailed(
                "Invalid or expired access token."
            )

        if not user.is_active:
            raise PermissionDenied("This account is disabled.")

        return user, payload

    def authenticate_header(self, request):
        return "Bearer"
