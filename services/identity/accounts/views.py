
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import (
    ProfileSerializer,
    ProfileUpdateSerializer,
    UsernameChangeSerializer,
    PasswordChangeSerializer,
)
from accounts.authentication import RS256AccessTokenAuthentication
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from audit.models import ActivityLog
from auth_flow.rate_limits import (
    enforce_password_change_limit,
    LoginRateLimitExceeded,
    RateLimitDependencyUnavailable,
    enforce_recovery_code_limit,
)
from auth_flow.services import change_user_password, InvalidCredentials,regenerate_recovery_code

def validation_error_response(details):
    return Response(
        {
            "error": {
                "code": "validation_error",
                "message": "The request contains invalid fields.",
                "details": details,
            }
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


class CurrentUserProfileView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = ProfileSerializer(request.user)
        return Response({"user": serializer.data})

    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )

        if not serializer.is_valid():
            return validation_error_response(serializer.errors)

        serializer.save()

        return Response(
            {"user": ProfileSerializer(request.user).data},
            status=status.HTTP_200_OK,
        )


class PublicUserProfileView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, username):
        user = User.objects.filter(
            username_normalized=username.strip().lower()
        ).first()

        if user is None:
            return Response(
                {
                    "error": {
                        "code": "not_found",
                        "message": "User not found.",
                        "details": {},
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"user": ProfileSerializer(user).data},
            status=status.HTTP_200_OK,
        )
class UsernameChangeView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UsernameChangeSerializer(data=request.data)

        if not serializer.is_valid():
            return validation_error_response(serializer.errors)

        new_username = serializer.validated_data["username"]
        user = request.user

        if new_username == user.username:
            return Response(
                {
                    "error": {
                        "code": "same_username",
                        "message": "Choose a different username.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        latest_change = ActivityLog.objects.filter(
            actor_id=user.id,
            action="username_changed",
            target_type="user",
            target_id=user.id,
        ).order_by("-created_at").first()

        if latest_change:
            next_change_at = latest_change.created_at + timedelta(days=30)

            if timezone.now() < next_change_at:
                return Response(
                    {
                        "error": {
                            "code": "username_change_too_soon",
                            "message": (
                                "You can change your username once every "
                                "30 days."
                            ),
                            "next_change_at": next_change_at.isoformat(),
                        }
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        try:
            with transaction.atomic():
                user.username = new_username
                user.save(update_fields=[
                    "username",
                    "username_normalized",
                    "updated_at",
                ])

                ActivityLog.objects.create(
                    actor_id=user.id,
                    action="username_changed",
                    target_type="user",
                    target_id=user.id,
                    metadata={
                        "old_username": request.user.username,
                        "new_username": new_username,
                    },
                )
        except Exception:
            raise

        return Response(
            {"user": ProfileSerializer(user).data},
            status=status.HTTP_200_OK,
        )



class PasswordChangeView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={"user": request.user},
        )
        serializer.is_valid(raise_exception=True)

        try:
            enforce_password_change_limit(request.user.id)

            
            change_user_password(
                user=request.user,
                current_password=serializer.validated_data["current_password"],
                new_password=serializer.validated_data["new_password"],
                current_session_id=request.auth["sid"],
            )

        except LoginRateLimitExceeded as exc:
            return Response(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": str(exc.detail),
                        "details": {},
                    }
                },
                status=429,
                headers={"Retry-After": str(exc.retry_after)},
            )
        except RateLimitDependencyUnavailable as exc:
            return Response(
                {
                    "error": {
                        "code": "dependency_unavailable",
                        "message": str(exc.detail),
                        "details": {},
                    }
                },
                status=503,
            )
        except InvalidCredentials as exc:
            return Response(
                {
                    "error": {
                        "code": "invalid_credentials",
                        "message": str(exc.detail),
                        "details": {},
                    }
                },
                status=401,
            )

        return Response(
            {"message": "Password changed successfully."},
            status=200,
        )

class RecoveryCodeRegenerationView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            enforce_recovery_code_limit(request.user.id)
            recovery_code = regenerate_recovery_code(user=request.user)
        except LoginRateLimitExceeded as exc:
            return Response(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": str(exc.detail),
                        "details": {},
                    }
                },
                status=429,
                headers={"Retry-After": str(exc.retry_after)},
            )
        except RateLimitDependencyUnavailable as exc:
            return Response(
                {
                    "error": {
                        "code": "dependency_unavailable",
                        "message": str(exc.detail),
                        "details": {},
                    }
                },
                status=503,
            )

        return Response(
            {
                "recovery_code": recovery_code,
                "recovery_code_notice": (
                    "Shown once. Store it somewhere safe."
                ),
            },
            status=200,
        )
