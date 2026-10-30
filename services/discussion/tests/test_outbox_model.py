from app.models import Outbox


def test_outbox_table_name():
    assert Outbox.__tablename__ == "outbox"


def test_outbox_has_expected_columns():
    expected_columns = {
        "id",
        "event_type",
        "payload",
        "created_at",
        "published_at",
    }

    actual_columns = set(Outbox.__table__.columns.keys())

    assert actual_columns == expected_columns


def test_outbox_payload_uses_jsonb():
    payload_type = Outbox.__table__.columns["payload"].type

    assert payload_type.__class__.__name__ == "JSONB"


def test_outbox_published_at_is_nullable():
    assert Outbox.__table__.columns["published_at"].nullable is True


def test_outbox_has_no_foreign_keys():
    assert len(Outbox.__table__.foreign_keys) == 0