import uuid
from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models


class RecoveryCode(models.Model):
    """Stores a user's recovery-code hash, never the original code."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="user_id",
        related_name="recovery_code",
    )
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "recovery_codes"

    def __str__(self):
        return f"Recovery code for user {self.user_id}"



class RefreshToken(models.Model):
    """Track refresh-token identifiers for rotation and revocation."""

    jti = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_column="user_id",
        related_name="refresh_tokens",
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "refresh_tokens"

    def __str__(self):
        return f"Refresh token {self.jti} for user {self.user_id}"
