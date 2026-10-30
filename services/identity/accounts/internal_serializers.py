from rest_framework import serializers

from accounts.models import User


class UserStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "role", "status"]
        read_only_fields = fields


class BatchUserLookupSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=100,
    )


class UsernameResolveSerializer(serializers.Serializer):
    usernames = serializers.ListField(
        child=serializers.CharField(
            max_length=30,
            min_length=3,
            trim_whitespace=True,
        ),
        allow_empty=False,
        max_length=100,
    )

    def validate_usernames(self, value):
        return [username.strip() for username in value]


class PublicUserSnippetSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "display_name", "avatar_url"]
        read_only_fields = fields


class ResolvedUsernameSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username"]
        read_only_fields = fields