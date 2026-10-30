from django.db.models import Q

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.service_authentication import (
    InternalServiceAuthentication,
)

from accounts.internal_serializers import (
    UserStatusSerializer,
    BatchUserLookupSerializer,
    UsernameResolveSerializer,
    PublicUserSnippetSerializer,
    ResolvedUsernameSerializer,
)


class InternalServiceAPIView(APIView):
    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [IsAuthenticated]

    allowed_services = set()

    def check_caller(self, request):
        service_name = request.user.service_name

        if service_name not in self.allowed_services:
            return Response(
                {
                    "error": {
                        "code": "SERVICE_FORBIDDEN",
                        "message": "This service cannot access this endpoint.",
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return None


class InternalUserStatusView(InternalServiceAPIView):
    allowed_services = {"discussion", "notify", "realtime"}

    def get(self, request, user_id):
        denied_response = self.check_caller(request)

        if denied_response:
            return denied_response

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {
                    "error": {
                        "code": "USER_NOT_FOUND",
                        "message": "User not found.",
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UserStatusSerializer(user)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class InternalUserBatchView(InternalServiceAPIView):
    allowed_services = {"discussion"}

    def post(self, request):
        denied_response = self.check_caller(request)

        if denied_response:
            return denied_response

        request_serializer = BatchUserLookupSerializer(
            data=request.data
        )

        if not request_serializer.is_valid():
            return Response(
                request_serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_ids = request_serializer.validated_data["ids"]

        users = User.objects.filter(id__in=user_ids)

        # Preserve the order of IDs supplied by the caller.
        users_by_id = {str(user.id): user for user in users}
        ordered_users = [
            users_by_id[str(user_id)]
            for user_id in user_ids
            if str(user_id) in users_by_id
        ]

        response_serializer = PublicUserSnippetSerializer(
            ordered_users,
            many=True,
        )

        return Response(
            {"items": response_serializer.data},
            status=status.HTTP_200_OK,
        )


class InternalUsernameResolveView(InternalServiceAPIView):
    allowed_services = {"notify"}

    def post(self, request):
        denied_response = self.check_caller(request)

        if denied_response:
            return denied_response

        request_serializer = UsernameResolveSerializer(
            data=request.data
        )

        if not request_serializer.is_valid():
            return Response(
                request_serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        usernames = request_serializer.validated_data["usernames"]

        normalized_usernames = [
            username.lower() for username in usernames
        ]

        users = User.objects.filter(
            username_normalized__in=normalized_usernames
        )

        users_by_username = {
            user.username_normalized: user
            for user in users
        }

        ordered_users = [
            users_by_username[username]
            for username in normalized_usernames
            if username in users_by_username
        ]

        response_serializer = ResolvedUsernameSerializer(
            ordered_users,
            many=True,
        )

        return Response(
            {"items": response_serializer.data},
            status=status.HTTP_200_OK,
        )