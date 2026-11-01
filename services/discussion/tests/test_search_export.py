from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services import forum_export_service as service
from app.api.routers import internal_export
from fastapi import HTTPException


def export_rows():
    author, thread_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    shared = dict(created_at=now, updated_at=now, author_id=author, thread_id=thread_id, parent_id=None)
    return [dict(shared, record_type='thread', record_id=thread_id, title='Thread', description='Body', body=None),
            dict(shared, record_type='comment', record_id=uuid4(), title='Thread', description=None, body='Reply')]


def database(rows):
    db = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    tags = MagicMock()
    tags.all.return_value = [(rows[0]['thread_id'], 'python')] if rows else []
    db.execute.side_effect = [result, tags]
    return db


@pytest.mark.asyncio
async def test_export_adds_username_to_threads_and_comments_with_one_batch(monkeypatch):
    rows = export_rows()
    profiles = AsyncMock(return_value=[{'id': str(rows[0]['author_id']), 'username': 'alice'}])
    monkeypatch.setattr(service, 'fetch_user_profiles', profiles)
    result = await service.export_for_search(database(rows))
    assert [item['author_username'] for item in result['items']] == ['alice', 'alice']
    assert result['items'][0]['tags'] == ['python']
    profiles.assert_awaited_once_with([str(rows[0]['author_id'])])


@pytest.mark.asyncio
async def test_empty_export_does_not_call_identity(monkeypatch):
    profiles = AsyncMock()
    monkeypatch.setattr(service, 'fetch_user_profiles', profiles)
    assert await service.export_for_search(database([])) == {'items': [], 'next_cursor': None}
    profiles.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_author_profile_refuses_incomplete_export(monkeypatch):
    monkeypatch.setattr(service, 'fetch_user_profiles', AsyncMock(return_value=[]))
    with pytest.raises(RuntimeError, match='author usernames'):
        await service.export_for_search(database(export_rows()))


@pytest.mark.asyncio
async def test_export_dependency_failure_is_safe_503(monkeypatch):
    monkeypatch.setattr(internal_export, 'export_for_search', AsyncMock(side_effect=RuntimeError('Private dependency detail')))
    with pytest.raises(HTTPException) as exc:
        await internal_export.export_for_search_endpoint(db=AsyncMock(), cursor=None, limit=20)
    assert exc.value.status_code == 503
    assert exc.value.detail['error']['code'] == 'dependency_unavailable'
    assert 'Private' not in str(exc.value.detail)
