import json
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.identity import resolve_usernames
from app.models import Notification, Outbox, ProcessedEvent
from app.notify.services.mention_parser import extract_mentions


CONSUMER_NAME = "notify"


def to_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(str(value))


async def process_event(
    session: AsyncSession,
    envelope: dict,
) -> None:
    event_id = to_uuid(envelope["event_id"])
    event_type = envelope["type"]
    payload = envelope["payload"]

    if event_type not in {"thread.created", "comment.created"}:
        return

    actor_id = to_uuid(
        payload["author_id"]
    )

    thread_id = to_uuid(
        payload["thread_id"]
    )

    comment_id = (
        to_uuid(payload["comment_id"])
        if event_type == "comment.created"
        else None
    )

    # Check whether this event was already processed.
    existing = await session.get(
        ProcessedEvent,
        {
            "event_id": event_id,
            "consumer": CONSUMER_NAME,
        },
    )

    if existing:
        return

    body = (
        payload.get("description", "")
        if event_type == "thread.created"
        else payload.get("body", "")
    )

    # Resolve mentioned usernames through Identity.
    usernames = extract_mentions(body)
    resolved_users = await resolve_usernames(usernames)

    # Map recipient ID -> notification type.
    recipients: dict[uuid.UUID, str] = {}

    # Thread replies notify the thread author.
    # Comment replies notify the parent comment author.
    if event_type == "comment.created":
        parent_id = payload.get("parent_id")

        reply_recipient = (
            payload.get("parent_author_id")
            if parent_id
            else payload.get("thread_author_id")
        )

        if reply_recipient:
            recipient_id = to_uuid(reply_recipient)

            if recipient_id != actor_id:
                recipients[recipient_id] = (
                    "reply_comment" if parent_id else "reply_thread"
                )

    # Mentions take precedence if a user is also the reply recipient.
    for user in resolved_users.values():
        recipient_id = to_uuid(user["id"])

        if recipient_id != actor_id:
            recipients[recipient_id] = "mention"

    # One transaction: notifications, deduplication, and live outbox.
    for recipient_id, notification_type in recipients.items():
        statement = (
            insert(Notification)
            .values(
                id=uuid.uuid4(),
                recipient_id=recipient_id,
                type=notification_type,
                actor_id=actor_id,
                thread_id=thread_id,
                comment_id=comment_id,
                source_event_id=event_id,
            )
            .on_conflict_do_nothing(
                constraint="uq_notification_recipient_source_event"
            )
            .returning(Notification.id)
        )

        result = await session.execute(statement)
        notification_id = result.scalar_one_or_none()

        # Only publish a live message when a new notification was inserted.
        if notification_id:
            session.add(
                Outbox(
                    id=uuid.uuid4(),
                    event_type="notification.created",
                    payload={
                        "target": f"ws:user:{recipient_id}",
                        "event": {
                            "type": "notification",
                            "data": {
                                "id": str(notification_id),
                                "type": notification_type,
                                "actor_id": str(actor_id),
                                "thread_id": str(thread_id),
                                "comment_id": (
                                    str(comment_id) if comment_id else None
                                ),
                            },
                        },
                    },
                )
            )

    session.add(
        ProcessedEvent(
            event_id=event_id,
            consumer=CONSUMER_NAME,
        )
    )

    await session.flush()