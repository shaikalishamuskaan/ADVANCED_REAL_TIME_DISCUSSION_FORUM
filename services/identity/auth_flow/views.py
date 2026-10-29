
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from auth_flow.rate_limits import (
    RateLimitExceeded,
    LoginRateLimitExceeded,
    RateLimitDependencyUnavailable,
    enforce_registration_limit,
    enforce_login_ip_limit,
    check_login_failure_limit,
    record_login_failure,
    clear_login_failures,
    enforce_password_reset_limits,
)
from auth_flow.serializers import RegistrationSerializer, LoginSerializer,PasswordResetSerializer
from auth_flow.services import (
    RegistrationConflict,
    register_user,
    authenticate_user,
    create_login_tokens,
    AccountDisabled,
    InvalidCredentials,
    rotate_refresh_token,
    revoke_refresh_token,
    InvalidRecoveryCode,
    reset_password,
)




def error_response(code, message, status_code, retry_after=None):
    response = Response(
        {
            "error": {
                "code": code,
                "message": str(message),
                "details": {},
            }
        },
        status=status_code,
    )
    if retry_after is not None:
        response["Retry-After"] = str(retry_after)
    return response


class RegisterView(APIView):
    """Handle new-user registration requests."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        ip_address = request.META.get("REMOTE_ADDR", "unknown")

        try:
            enforce_registration_limit(ip_address)
        except RateLimitExceeded as exc:
            return error_response(
                "rate_limited", exc.detail, 429, exc.retry_after
            )

        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user, recovery_code = register_user(
                username=serializer.validated_data["username"],
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
                display_name=serializer.validated_data["display_name"],
            )
        except RegistrationConflict as exc:
            return error_response(
                exc.default_code, exc.detail, exc.status_code
            )

        return Response(
            {
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "display_name": user.display_name,
                    "role": user.role,
                    "status": user.status,
                    "avatar_url": user.avatar_url,
                    "bio": user.bio,
                },
                "recovery_code": recovery_code,
                "recovery_code_notice": "Shown once. Store it somewhere safe.",
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """Authenticate a user and issue access and refresh tokens."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        ip_address = request.META.get("REMOTE_ADDR", "unknown")

        try:
            enforce_login_ip_limit(ip_address)

            serializer = LoginSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            email = serializer.validated_data["email"]
            password = serializer.validated_data["password"]

            check_login_failure_limit(email)

            user = authenticate_user(email, password)

            if user is None:
                record_login_failure(email)
                return error_response(
                    "invalid_credentials",
                    "Invalid email or password.",
                    401,
                )

            clear_login_failures(email)
            access_token, refresh_token = create_login_tokens(user)

        except LoginRateLimitExceeded as exc:
            return error_response(
                "rate_limited", exc.detail, 429, exc.retry_after
            )
        except RateLimitDependencyUnavailable as exc:
            return error_response(
                "dependency_unavailable", exc.detail, 503
            )
        except AccountDisabled as exc:
            return error_response(
                "account_disabled", exc.detail, 403
            )

        response = Response(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": settings.ACCESS_TOKEN_TTL_SECONDS,
            },
            status=200,
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            max_age=settings.REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60,
            httponly=True,
            secure=True,
            samesite="Strict",
            path="/api/auth",
        )
        return response


class RefreshView(APIView):
    """Rotate the refresh token and return a new access token."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        origin = request.headers.get("Origin")
        allowed_origins = getattr(settings, "CORS_ALLOWED_ORIGINS", [])

        if not origin or origin not in allowed_origins:
            return error_response(
                "origin_not_allowed",
                "The request origin is not allowed.",
                403,
            )

        raw_token = request.COOKIES.get("refresh_token")
        if not raw_token:
            return error_response(
                "invalid_credentials",
                "A valid refresh token is required.",
                401,
            )

        try:
            access_token, new_refresh_token = rotate_refresh_token(
                raw_token
            )
        except InvalidCredentials as exc:
            return error_response(
                "invalid_credentials", exc.detail, 401
            )
        except AccountDisabled as exc:
            return error_response(
                "account_disabled", exc.detail, 403
            )

        response = Response(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": settings.ACCESS_TOKEN_TTL_SECONDS,
            },
            status=200,
        )
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            max_age=settings.REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60,
            httponly=True,
            secure=True,
            samesite="Strict",
            path="/api/auth",
        )
        return response

class LogoutView(APIView):
    """Revoke the current refresh token and clear its cookie."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        raw_token = request.COOKIES.get("refresh_token")

        if raw_token:
            revoke_refresh_token(raw_token)

        response = Response(status=204)
        response.delete_cookie(
            key="refresh_token",
            path="/api/auth",
            samesite="Strict",
        )
        return response

class PasswordResetView(APIView):
    """Reset a password using the user's recovery code."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        ip_address = request.META.get("REMOTE_ADDR", "unknown")

        try:
            enforce_password_reset_limits(
                data["username"],
                ip_address,
            )
            replacement_code = reset_password(
                username=data["username"],
                recovery_code=data["recovery_code"],
                new_password=data["new_password"],
            )
        except LoginRateLimitExceeded as exc:
            return error_response(
                "rate_limited",
                exc.detail,
                429,
                exc.retry_after,
            )
        except RateLimitDependencyUnavailable as exc:
            return error_response(
                "dependency_unavailable",
                exc.detail,
                503,
            )
        except InvalidRecoveryCode as exc:
            return error_response(
                "invalid_reset_code",
                exc.detail,
                400,
            )
        except RegistrationConflict as exc:
            return error_response(
                exc.default_code,
                exc.detail,
                exc.status_code,
            )

        return Response(
            {
                "message": "Password reset successfully.",
                "recovery_code": replacement_code,
                "recovery_code_notice": (
                    "This replacement code is shown once. Store it safely."
                ),
            },
            status=200,
        )
