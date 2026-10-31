import base64
import json
from datetime import datetime
from uuid import UUID


def encode_cursor(created_at: datetime, thread_id: UUID) -> str:
    payload = {
        "created_at": created_at.isoformat(),
        "id": str(thread_id),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))

        created_at = datetime.fromisoformat(payload["created_at"])
        thread_id = UUID(payload["id"])

        if created_at.tzinfo is None:
            raise ValueError("Cursor timestamp must include a timezone.")

        return created_at, thread_id

    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid pagination cursor.") from exc