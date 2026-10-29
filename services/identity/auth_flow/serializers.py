
import re

from rest_framework import serializers


class RegistrationSerializer(serializers.Serializer):
    """Validate the public registration request."""

    username = serializers.CharField(
        min_length=3,
        max_length=30,
        trim_whitespace=True,
    )
    email = serializers.EmailField(
        max_length=254,
        trim_whitespace=True,
    )
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )
    display_name = serializers.CharField(
        max_length=100,
        trim_whitespace=True,
    )

    def validate_username(self, value):
        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", value):
            raise serializers.ValidationError(
                "Username must contain 3 to 30 letters, digits, or underscores."
            )
        return value

    def validate_email(self, value):
        return value.strip().lower()

    def validate_display_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                "Display name cannot be empty."
            )
        return value.strip()

    def validate_password(self, value):
        if not value:
            raise serializers.ValidationError("Password cannot be empty.")
        return value

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    def validate_email(self, value):
        return value.strip().lower()

class PasswordResetSerializer(serializers.Serializer):
    username = serializers.CharField(
        min_length=3,
        max_length=30,
        trim_whitespace=True,
    )
    recovery_code = serializers.CharField(
        min_length=19,
        max_length=19,
        trim_whitespace=True,
        write_only=True,
    )
    new_password = serializers.CharField(
        min_length=8,
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
    )

    def validate_username(self, value):
        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", value):
            raise serializers.ValidationError(
                "Username must contain 3 to 30 letters, digits, or underscores."
            )
        return value.strip()

    def validate_recovery_code(self, value):
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}", normalized):
            raise serializers.ValidationError(
                "Enter a recovery code in XXXX-XXXX-XXXX-XXXX format."
            )
        return normalized
