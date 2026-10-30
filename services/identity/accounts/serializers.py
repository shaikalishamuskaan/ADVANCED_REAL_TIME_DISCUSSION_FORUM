
from rest_framework import serializers

from accounts.models import User


class ProfileSerializer(serializers.ModelSerializer):
    """Fields safe to return in a profile response."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "role",
            "status",
            "avatar_url",
            "bio",
        ]
        read_only_fields = fields


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Fields a user is allowed to change on their own profile."""

    avatar_url = serializers.URLField(
        max_length=2048,
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    class Meta:
        model = User
        fields = ["display_name", "bio", "avatar_url"]
        extra_kwargs = {
            "display_name": {
                "required": False,
                "allow_blank": False,
                "max_length": 100,
            },
            "bio": {
                "required": False,
            },
        }

    def validate_display_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(
                "Display name cannot be empty."
            )
        return value

    def validate(self, attrs):
        allowed_fields = {"display_name", "bio", "avatar_url"}
        unexpected_fields = set(self.initial_data.keys()) - allowed_fields

        if unexpected_fields:
            raise serializers.ValidationError({
                field: "This field cannot be updated."
                for field in unexpected_fields
            })

        return attrs
class UsernameChangeSerializer(serializers.Serializer):
    username = serializers.RegexField(
        regex=r"^[A-Za-z0-9_]{3,30}$",
        max_length=30,
        min_length=3,
        error_messages={
            "invalid": (
                "Username must contain 3 to 30 letters, "
                "digits, or underscores."
            ),
        },
    )

    def validate_username(self, value):
        username = value.strip()
        normalized = username.lower()

        if User.objects.filter(username_normalized=normalized).exists():
            raise serializers.ValidationError(
                "This username is already taken."
            )

        return username



class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )



class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            validate_password(value, user=self.context.get("user"))
        except ValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc

        return value
