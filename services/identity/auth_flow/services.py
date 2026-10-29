
import hashlib
import hmac
import os
import secrets
import string

from django.conf import settings
from django.utils import timezone
import jwt

from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException

from accounts.models import User
from audit.models import ActivityLog
from auth_flow.models import RecoveryCode,RefreshToken
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from django.contrib.auth import get_user_model

from auth_flow.tokens import create_access_token, create_refresh_token,decode_refresh_token


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


class InvalidCredentials(APIException):
    status_code = 401
    default_code = "invalid_credentials"
    default_detail = "Invalid email or password."


class AccountDisabled(APIException):
    status_code = 403
    default_code = "account_disabled"
    default_detail = "This account is disabled."


@transaction.atomic
def authenticate_user(email, password):
    """Validate credentials and issue tokens for an active user."""
    user = User.objects.filter(email=email.strip().lower()).first()

    # Use the same response for unknown emails and incorrect passwords.
    if user is None or not user.check_password(password):
        return None

    if user.status != "active":
        raise AccountDisabled()

    return user


@transaction.atomic
def create_login_tokens(user):
    """Create persisted refresh-token state and an access token."""
    refresh_token = create_refresh_token(user)
    access_token = create_access_token(user)

    ActivityLog.objects.create(
        actor_id=user.id,
        action="login",
        target_type="user",
        target_id=user.id,
        metadata={},
    )

    return access_token, refresh_token

class InvalidCredentials(APIException):
    status_code = 401
    default_code = "invalid_credentials"
    default_detail = "Invalid email or password."


class AccountDisabled(APIException):
    status_code = 403
    default_code = "account_disabled"
    default_detail = "This account is disabled."


def authenticate_user(email, password):
    """Return an active user or raise the appropriate login error."""
    user = User.objects.filter(email=email.strip().lower()).first()

    if user is None or not user.check_password(password):
        return None

    if user.status != "active":
        raise AccountDisabled()

    return user


@transaction.atomic
def create_login_tokens(user):
    """Issue tokens and record the successful login."""
    refresh_token = create_refresh_token(user)
    access_token = create_access_token(user)

    ActivityLog.objects.create(
        actor_id=user.id,
        action="login",
        target_type="user",
        target_id=user.id,
        metadata={},
    )

    return access_token, refresh_token


@transaction.atomic

def rotate_refresh_token(raw_token):
    """Rotate refresh tokens and persist reuse detection."""
    try:
        payload = decode_refresh_token(raw_token)
    except jwt.InvalidTokenError as exc:
        raise InvalidCredentials() from exc

    token_id = payload.get("jti")
    reuse_detected = False
    result = None

    with transaction.atomic():
        try:
            token_record = (
                RefreshToken.objects.select_for_update()
                .select_related("user")
                .get(jti=token_id)
            )
        except (RefreshToken.DoesNotExist, ValueError) as exc:
            raise InvalidCredentials() from exc

        user = token_record.user

        if str(user.id) != payload.get("sub"):
            raise InvalidCredentials()

        if token_record.revoked_at is not None:
            now = timezone.now()
            RefreshToken.objects.filter(
                user=user,
                revoked_at__isnull=True,
            ).update(revoked_at=now)

            ActivityLog.objects.create(
                actor_id=user.id,
                action="refresh_reuse_detected",
                target_type="user",
                target_id=user.id,
                metadata={},
            )
            reuse_detected = True

        elif token_record.expires_at <= timezone.now():
            raise InvalidCredentials()

        elif user.status != "active":
            raise AccountDisabled()

        else:
            token_record.revoked_at = timezone.now()
            token_record.save(update_fields=["revoked_at"])

            new_refresh_token = create_refresh_token(user)
            new_access_token = create_access_token(user)
            result = (new_access_token, new_refresh_token)

    # Raise only after the reuse-detection transaction has committed.
    if reuse_detected:
        raise InvalidCredentials()

    return result

def revoke_refresh_token(raw_token):
    """Revoke a refresh token if it is valid and still active."""
    import jwt

    try:
        payload = decode_refresh_token(raw_token)
    except jwt.InvalidTokenError:
        # Logout should still succeed for an invalid or expired cookie.
        return

    token_id = payload.get("jti")
    if not token_id:
        return

    with transaction.atomic():
        try:
            token_record = (
                RefreshToken.objects.select_for_update()
                .get(jti=token_id)
            )
        except (RefreshToken.DoesNotExist, ValueError):
            return

        if str(token_record.user_id) != payload.get("sub"):
            return

        if token_record.revoked_at is None:
            token_record.revoked_at = timezone.now()
            token_record.save(update_fields=["revoked_at"])


class InvalidRecoveryCode(APIException):
    status_code = 400
    default_code = "invalid_reset_code"
    default_detail = "The username or recovery code is invalid."


@transaction.atomic
def reset_password(*, username, recovery_code, new_password):
    """Reset a user's password and replace their one-time recovery code."""
    normalized_username = username.strip()
    user = (
        User.objects.select_for_update()
        .filter(username_normalized=normalized_username.lower())
        .first()
    )

    if user is None:
        raise InvalidRecoveryCode()

    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise RegistrationConflict(
            "validation_error",
            "The new password does not meet the password requirements.",
        ) from exc

    try:
        stored_code = (
            RecoveryCode.objects.select_for_update()
            .get(user=user)
        )
    except RecoveryCode.DoesNotExist as exc:
        raise InvalidRecoveryCode() from exc

    submitted_hash = hash_recovery_code(recovery_code)

    if not hmac.compare_digest(stored_code.code_hash, submitted_hash):
        raise InvalidRecoveryCode()

    if (
        stored_code.expires_at is not None
        and stored_code.expires_at <= timezone.now()
    ):
        raise InvalidRecoveryCode()

    # Replace the password and invalidate all existing refresh sessions.
    user.set_password(new_password)
    user.save(update_fields=["password"])

    RefreshToken.objects.filter(
        user=user,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())

    # Generate a replacement recovery code; reveal it only in this response.
    replacement_code = generate_recovery_code()
    stored_code.code_hash = hash_recovery_code(replacement_code)
    stored_code.expires_at = None
    stored_code.save(update_fields=["code_hash", "expires_at"])

    ActivityLog.objects.create(
        actor_id=user.id,
        action="password_reset",
        target_type="user",
        target_id=user.id,
        metadata={},
    )

    return replacement_code
