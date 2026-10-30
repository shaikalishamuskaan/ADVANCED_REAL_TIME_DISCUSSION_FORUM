from django.db import transaction
import base64
from accounts.models import User
from audit.models import ActivityLog, Outbox
from django.utils import timezone
from auth_flow.models import RefreshToken,RecoveryCode
from datetime import timedelta
import uuid
from django.db.models import Q
from datetime import timezone as datetime_timezone
from django.utils.dateparse import parse_datetime

from auth_flow.services import generate_recovery_code, hash_recovery_code
@transaction.atomic
def change_user_role(*, actor, user, new_role):
    old_role = user.role

    if old_role == new_role:
        return user

    user.role = new_role
    user.save(update_fields=["role", "updated_at"])

    ActivityLog.objects.create(
        actor_id=actor.id,
        action="role_changed",
        target_type="user",
        target_id=user.id,
        metadata={
            "old_role": old_role,
            "new_role": new_role,
        },
    )

    Outbox.objects.create(
        event_type="user.role_changed",
        payload={
            "user_id": str(user.id),
            "old_role": old_role,
            "new_role": new_role,
        },
    )

    return user
@transaction.atomic
def disable_user_account(*, actor, user, reason):
    # Avoid duplicate logs and events if already disabled.
    if user.status == User.Status.DISABLED:
        return user

    now = timezone.now()

    # Disable the account.
    user.status = User.Status.DISABLED
    user.save(update_fields=["status", "updated_at"])

    # Revoke every refresh token that has not already been revoked.
    RefreshToken.objects.filter(
        user=user,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    # Record the admin action.
    ActivityLog.objects.create(
        actor_id=actor.id,
        action="user_disabled",
        target_type="user",
        target_id=user.id,
        metadata={"reason": reason},
    )

    # Queue the event for the Outbox relay.
    Outbox.objects.create(
        event_type="user.disabled",
        payload={"user_id": str(user.id)},
    )

    return user

@transaction.atomic
def enable_user_account(*, actor, user):
    # Avoid duplicate logs and events if already active.
    if user.status == User.Status.ACTIVE:
        return user

    user.status = User.Status.ACTIVE
    user.save(update_fields=["status", "updated_at"])

    ActivityLog.objects.create(
        actor_id=actor.id,
        action="user_enabled",
        target_type="user",
        target_id=user.id,
        metadata={},
    )

    Outbox.objects.create(
        event_type="user.enabled",
        payload={"user_id": str(user.id)},
    )

    return user

@transaction.atomic
def issue_admin_recovery_code(*, actor, user):
    """Issue a one-time recovery code that expires after 24 hours."""
    now = timezone.now()
    recovery_code = generate_recovery_code()

    stored_code, _ = RecoveryCode.objects.select_for_update().get_or_create(
        user=user,
        defaults={
            "code_hash": hash_recovery_code(recovery_code),
            "expires_at": now + timedelta(hours=24),
        },
    )

    # Replace the previous code, making it invalid immediately.
    stored_code.code_hash = hash_recovery_code(recovery_code)
    stored_code.expires_at = now + timedelta(hours=24)
    stored_code.save(update_fields=["code_hash", "expires_at"])

    ActivityLog.objects.create(
        actor_id=actor.id,
        action="admin_recovery_code_issued",
        target_type="user",
        target_id=user.id,
        metadata={"expires_at": stored_code.expires_at.isoformat()},
    )

    return recovery_code



# Only forum-related actions will be visible to moderators.
# Add actual action names here when the Discussion service implements them.
MODERATOR_FORUM_ACTIONS = {
    "thread_created",
    "thread_updated",
    "thread_deleted",
    "comment_created",
    "comment_updated",
    "comment_deleted",
    "thread_liked",
    "thread_unliked",
    "comment_liked",
    "comment_unliked",
    "report_created",
    "report_resolved",
    "report_dismissed",
}


PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def encode_activity_cursor(activity):
    cursor_data = (
        f"{activity.created_at.isoformat()}|{activity.id}"
    )
    encoded = base64.urlsafe_b64encode(
        cursor_data.encode("utf-8")
    ).decode("utf-8")

    return encoded.rstrip("=")


def decode_activity_cursor(cursor):
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)

        decoded = base64.urlsafe_b64decode(
            padded_cursor.encode("utf-8")
        ).decode("utf-8")

        timestamp, activity_id = decoded.rsplit("|", 1)

        created_at = parse_datetime(timestamp)

        if created_at is None or created_at.tzinfo is None:
            raise ValueError("Invalid timestamp")

        activity_uuid = uuid.UUID(activity_id)

        return created_at, activity_uuid

    except (ValueError, TypeError, UnicodeDecodeError):
        raise ValueError("Invalid activity cursor")


def get_activity_logs(
    *,
    actor_id=None,
    action=None,
    target_type=None,
    cursor=None,
    moderator=False,
):
    logs = ActivityLog.objects.all()

    if moderator:
        logs = logs.filter(action__in=MODERATOR_FORUM_ACTIONS)

    if actor_id:
        logs = logs.filter(actor_id=actor_id)

    if action:
        logs = logs.filter(action=action)

    if target_type:
        logs = logs.filter(target_type=target_type)

    logs = logs.order_by("-created_at", "-id")

    if cursor:
        created_at, activity_id = decode_activity_cursor(cursor)

        logs = logs.filter(
            Q(created_at__lt=created_at)
            | Q(
                created_at=created_at,
                id__lt=activity_id,
            )
        )

    page = list(logs[: PAGE_SIZE + 1])

    has_more = len(page) > PAGE_SIZE
    items = page[:PAGE_SIZE]

    next_cursor = (
        encode_activity_cursor(items[-1])
        if has_more and items
        else None
    )

    return {
        "items": items,
        "next_cursor": next_cursor,
    }