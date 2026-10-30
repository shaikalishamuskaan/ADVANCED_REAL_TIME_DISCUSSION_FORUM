
from rest_framework import serializers

from accounts.models import User
from audit.models import ActivityLog

class AdminUserSerializer(serializers.ModelSerializer):
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
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
class ChangeUserRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=User.Role.choices)


class DisableUserSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=500,
        trim_whitespace=True,
        allow_blank=False,
    )




class ActivityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "actor_id",
            "action",
            "target_type",
            "target_id",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields