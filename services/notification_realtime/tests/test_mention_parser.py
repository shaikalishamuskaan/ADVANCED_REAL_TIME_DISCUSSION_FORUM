import pytest

from app.notify.services.mention_parser import extract_mentions


def test_extract_single_mention():
    assert extract_mentions("Hello @sara_dev") == ["sara_dev"]


def test_extract_multiple_mentions():
    assert extract_mentions("Hello @sara_dev and @omar") == [
        "sara_dev",
        "omar",
    ]


def test_duplicate_mentions_are_removed():
    assert extract_mentions("@sara_dev hello @sara_dev") == ["sara_dev"]


def test_email_addresses_are_not_mentions():
    assert extract_mentions("Contact test@example.com") == []


def test_inline_code_mentions_are_ignored():
    assert extract_mentions("Use `@hidden` and mention @sara_dev") == [
        "sara_dev"
    ]


def test_fenced_code_mentions_are_ignored():
    body = "Hello @omar\n```python\n@hidden\n```\n@Sara"
    assert extract_mentions(body) == ["omar", "Sara"]


def test_maximum_ten_mentions():
    body = " ".join(f"@user{i:02d}" for i in range(1, 13))
    assert len(extract_mentions(body)) == 10


def test_invalid_username_length_is_ignored():
    assert extract_mentions("@ab @thisusernameiswaytoolongtobevalid123") == []