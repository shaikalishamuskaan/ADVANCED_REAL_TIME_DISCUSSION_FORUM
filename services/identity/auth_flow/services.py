
import hashlib
import hmac
import os
import secrets
import string

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException

from accounts.models import User
from audit.models import ActivityLog
from auth_flow.models import RecoveryCode


class RegistrationConflict(APIException):
    status_code = 409

    def __init__(self, code, message):
        self.default_code = code
        self.default_detail = message
        super().__init__(detail=message, code=code)



def generate_recovery_code():
    """Generate a high-entropy recovery code in XXXX-XXXX-XXXX-XXXX format."""
    alphabet = string.ascii_uppercase + string.digits
    groups = [
        "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(4)
    ]
    return "-".join(groups)


def hash_recovery_code(code):
    """Hash a recovery code using the server-side HMAC secret."""
    key = os.getenv("RECOVERY_CODE_HMAC_KEY")
    if not key:
        raise RuntimeError("RECOVERY_CODE_HMAC_KEY is not configured.")

    return hmac.new(
        key.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@transaction.atomic
def register_user(*, username, email, password, display_name):
    """Create a user, recovery-code hash, and activity log atomically."""
    normalized_username = username.strip()
    normalized_email = email.strip().lower()

    
    if User.objects.filter(
        username_normalized=normalized_username.lower()
    ).exists():
        raise RegistrationConflict(
            "username_taken",
            "This username is already taken.",
        )

    if User.objects.filter(email=normalized_email).exists():
        raise RegistrationConflict(
            "email_taken",
            "This email address is already registered.",
        )

    recovery_code = generate_recovery_code()

    try:
        user = User.objects.create_user(
            username=normalized_username,
            email=normalized_email,
            password=password,
            display_name=display_name.strip(),
        )

        RecoveryCode.objects.create(
            user=user,
            code_hash=hash_recovery_code(recovery_code),
            expires_at=None,
        )

        ActivityLog.objects.create(
            actor_id=user.id,
            action="account_created",
            target_type="user",
            target_id=user.id,
            metadata={},
        )
    
    except IntegrityError as exc:
        # The database uniqueness constraints also protect concurrent requests.
        raise RegistrationConflict(
            "conflict",
            "An account with this username or email already exists.",
        ) from exc


    return user, recovery_code
