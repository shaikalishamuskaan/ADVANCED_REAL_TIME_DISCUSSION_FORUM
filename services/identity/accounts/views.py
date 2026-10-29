
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import (
    ProfileSerializer,
    ProfileUpdateSerializer,
)
from accounts.authentication import RS256AccessTokenAuthentication


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
