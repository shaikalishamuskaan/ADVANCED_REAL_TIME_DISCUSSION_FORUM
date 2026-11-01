from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from app.clients.discussion_export import DiscussionExportClient


def thread_record():
    return dict(type='thread', id=str(uuid4()), author_id=str(uuid4()), author_username='alice',
                title='Exported thread', description='Exported body', tags=['python'],
                created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())


@pytest.mark.asyncio
async def test_export_paginates_using_service_key_and_opaque_cursor():
    requests = []
    record = thread_record()
    def respond(request):
        requests.append(request)
        if 'cursor' not in request.url.params:
            return httpx.Response(200, json={'items': [record], 'next_cursor': 'opaque-cursor'})
        return httpx.Response(200, json={'items': [], 'next_cursor': None})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url='http://discussion') as client:
        pages = [page async for page in DiscussionExportClient(client, 'test-service-key').pages()]
    assert len(pages) == 2
    assert len(pages[0].items) == 1
    assert all(request.url.path == '/internal/forum/export' for request in requests)
    assert all(request.headers['X-Service-Key'] == 'test-service-key' for request in requests)
    assert requests[0].url.params['limit'] == '50'
    assert requests[1].url.params['cursor'] == 'opaque-cursor'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 503])
async def test_export_http_errors_propagate(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status)), base_url='http://discussion') as client:
        with pytest.raises(httpx.HTTPStatusError):
            _ = [page async for page in DiscussionExportClient(client, 'test-key').pages()]


@pytest.mark.asyncio
async def test_repeated_cursor_is_rejected():
    page = {'items': [thread_record()], 'next_cursor': 'same-cursor'}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page)), base_url='http://discussion') as client:
        with pytest.raises(ValueError, match='non-advancing'):
            _ = [item async for item in DiscussionExportClient(client, 'test-key').pages()]


@pytest.mark.asyncio
async def test_missing_username_is_not_invented():
    record = thread_record()
    record.pop('author_username')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'items': [record], 'next_cursor': None})), base_url='http://discussion') as client:
        with pytest.raises(ValueError):
            _ = [page async for page in DiscussionExportClient(client, 'test-key').pages()]


def test_service_key_is_required_before_any_request():
    with pytest.raises(ValueError, match='SEARCH_SERVICE_KEY'):
        DiscussionExportClient(None, '')
