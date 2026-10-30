
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
import uuid
from accounts.authentication import RS256AccessTokenAuthentication
from accounts.models import User
from admin_console.serializers import AdminUserSerializer,ChangeUserRoleSerializer,DisableUserSerializer,ActivityLogSerializer
from admin_console.services import change_user_role,disable_user_account,enable_user_account,issue_admin_recovery_code,get_activity_logs

def error_response(code, message, details=None, http_status=status.HTTP_400_BAD_REQUEST):
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            }
        },
        status=http_status,
    )


class AdminUserListView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != User.Role.ADMIN:
            return error_response(
                "insufficient_role",
                "Administrator access is required.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        users = User.objects.all().order_by("username_normalized", "id")

        query = request.query_params.get("query", "").strip()
        role = request.query_params.get("role", "").strip().lower()
        account_status = request.query_params.get("status", "").strip().lower()

        if query:
            users = users.filter(username__icontains=query)

        if role:
            if role not in User.Role.values:
                return error_response(
                    "validation_error", "Invalid role filter.", {"role": role}
                )
            users = users.filter(role=role)

        if account_status:
            if account_status not in User.Status.values:
                return error_response(
                    "validation_error",
                    "Invalid status filter.",
                    {"status": account_status},
                )
            users = users.filter(status=account_status)

        cursor = request.query_params.get("cursor", "").strip()

        if cursor:
            try:
                last_user = User.objects.get(pk=cursor)
            except (User.DoesNotExist, ValueError, ValidationError):
                return error_response("invalid_cursor", "The cursor is invalid.")

            users = users.filter(
                Q(username_normalized__gt=last_user.username_normalized)
                | Q(
                    username_normalized=last_user.username_normalized,
                    id__gt=last_user.id,
                )
            )

        page = list(users[:21])
        has_more = len(page) > 20
        page = page[:20]

        return Response(
            {
                "users": AdminUserSerializer(page, many=True).data,
                "next_cursor": str(page[-1].id) if has_more and page else None,
            },
            status=status.HTTP_200_OK,
        )


class AdminUserRoleChangeView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, user_id):
        if request.user.role != User.Role.ADMIN:
            return error_response(
                "insufficient_role",
                "Administrator access is required.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        if str(request.user.id) == str(user_id):
            return error_response(
                "cannot_change_own_role",
                "Administrators cannot change their own role.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ChangeUserRoleSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "validation_error",
                "Invalid role.",
                serializer.errors,
            )

        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, ValidationError):
            return error_response(
                "user_not_found",
                "User not found.",
                http_status=status.HTTP_404_NOT_FOUND,
            )

        user = change_user_role(
            actor=request.user,
            user=user,
            new_role=serializer.validated_data["role"],
        )

        return Response(
            AdminUserSerializer(user).data,
            status=status.HTTP_200_OK,
        )

class AdminUserDisableView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        if request.user.role != User.Role.ADMIN:
            return error_response(
                "insufficient_role",
                "Only admins can disable users.",
                http_status=403,
            )

        if str(request.user.id) == str(user_id):
            return error_response(
                "cannot_disable_self",
                "Admins cannot disable their own accounts.",
                http_status=403,
            )

        serializer = DisableUserSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                "validation_error",
                "A valid reason is required.",
                serializer.errors,
            )

        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, ValidationError):
            return error_response(
                "user_not_found",
                "User not found.",
                http_status=404,
            )

        if user.role == User.Role.ADMIN:
            return error_response(
                "cannot_disable_admin",
                "Admins cannot disable another admin.",
                http_status=403,
            )

        user = disable_user_account(
            actor=request.user,
            user=user,
            reason=serializer.validated_data["reason"],
        )

        return Response(AdminUserSerializer(user).data, status=200)


class AdminUserEnableView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        if request.user.role != User.Role.ADMIN:
            return error_response(
                "insufficient_role",
                "Only admins can enable users.",
                http_status=403,
            )

        if str(request.user.id) == str(user_id):
            return error_response(
                "cannot_enable_self",
                "Admins cannot enable their own accounts.",
                http_status=403,
            )

        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, ValidationError):
            return error_response(
                "user_not_found",
                "User not found.",
                http_status=404,
            )

        if user.role == User.Role.ADMIN:
            return error_response(
                "cannot_enable_admin",
                "Admins cannot enable another admin through this endpoint.",
                http_status=403,
            )

        user = enable_user_account(
            actor=request.user,
            user=user,
        )

        return Response(AdminUserSerializer(user).data, status=200)

class AdminUserRecoveryCodeView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        if request.user.role != User.Role.ADMIN:
            return error_response(
                "insufficient_role",
                "Only admins can issue recovery codes.",
                http_status=403,
            )

        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, ValidationError):
            return error_response(
                "user_not_found",
                "User not found.",
                http_status=404,
            )

        recovery_code = issue_admin_recovery_code(
            actor=request.user,
            user=user,
        )

        return Response(
            {
                "recovery_code": recovery_code,
                "expires_in": 86400,
                "recovery_code_notice": (
                    "One-time code. Valid for 24 hours. "
                    "Shown once; communicate it to the user securely."
                ),
            },
            status=200,
        )
class AdminActivityLogView(APIView):
    authentication_classes = [RS256AccessTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):

        if request.user.role not in [
            User.Role.ADMIN,
            User.Role.MODERATOR,
        ]:
            return error_response(
                "insufficient_role",
                "Administrator or moderator access is required.",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        actor_id = request.query_params.get("actor_id", "").strip()
        action = request.query_params.get("action", "").strip()
        target_type = request.query_params.get(
            "target_type", ""
        ).strip()
        cursor = request.query_params.get("cursor", "").strip()

        if actor_id:
            try:
                uuid.UUID(actor_id)
            except ValueError:
                return error_response(
                    "validation_error",
                    "Invalid actor_id.",
                    {"actor_id": actor_id},
                )

        try:
            result = get_activity_logs(
                actor_id=actor_id or None,
                action=action or None,
                target_type=target_type or None,
                cursor=cursor or None,
                moderator=request.user.role == User.Role.MODERATOR,
            )

        except ValueError:
            return error_response(
                "invalid_cursor",
                "The activity log cursor is invalid.",
            )

        return Response(
            {
                "items": ActivityLogSerializer(
                    result["items"],
                    many=True,
                ).data,
                "next_cursor": result["next_cursor"],
            },
            status=status.HTTP_200_OK,
        )