import base64
from datetime import datetime
from uuid import UUID


def encode_cursor(created_at: datetime, document_id: UUID) -> str:
    value = f"{created_at.isoformat()}|{document_id}"
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True).decode()
        timestamp, document_id = raw.split("|", 1)
        created_at = datetime.fromisoformat(timestamp)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Missing cursor timezone")
        return created_at, UUID(document_id)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid cursor") from exc
