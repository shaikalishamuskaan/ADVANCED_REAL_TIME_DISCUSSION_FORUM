
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from auth_flow.serializers import RegistrationSerializer
from auth_flow.services import RegistrationConflict, register_user


class RegisterView(APIView):
    """Handle new-user registration requests."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
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
            raise ValidationError({
                "error": {
                    "code": "conflict",
                    "message": str(exc.detail),
                    "details": {},
                }
            })

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
