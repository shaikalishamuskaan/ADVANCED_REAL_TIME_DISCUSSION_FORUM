from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.domain.cursor import decode_cursor, encode_cursor


def test_cursor_round_trip():
    created_at = datetime.now(timezone.utc)
    thread_id = uuid4()

    cursor = encode_cursor(created_at, thread_id)
    decoded_at, decoded_id = decode_cursor(cursor)

    assert decoded_at == created_at
    assert decoded_id == thread_id


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-valid-cursor",
        "",
        "e30",  # Valid JSON, but missing required fields.
    ],
)
def test_invalid_cursor_is_rejected(cursor):
    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        decode_cursor(cursor)