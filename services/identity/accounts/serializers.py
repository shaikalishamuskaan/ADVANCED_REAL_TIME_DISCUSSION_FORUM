
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
