import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.discussion_export import DiscussionExportClient
from app.models import ProcessedEvent, SearchDocument
from app.services import index_events, index_lock
from app.services.rebuild import rebuild_index
from tests.test_database_integration import database, document, save
from tests.test_discussion_export import thread_record
from tests.test_index_events import event, documents, ledger

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get('RUN_SEARCH_INTEGRATION') != '1', reason='Set RUN_SEARCH_INTEGRATION=1; requires local PostgreSQL')]


@pytest.fixture(autouse=True)
def isolated_index_lock(monkeypatch):
    monkeypatch.setattr(index_lock, 'INDEX_LOCK_KEY', uuid4().int % (2**63))


async def rebuild(engine, handler):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://discussion') as client:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await rebuild_index(session, DiscussionExportClient(client, 'test-key'))


async def test_rebuild_handles_comments_first_removes_stale_docs_and_keeps_ledger(database):
    engine, schema = database
    old = document()
    processed = ProcessedEvent(event_id=uuid4(), consumer='search')
    await save(engine, old, processed)
    thread = thread_record()
    comment = dict(type='comment', id=str(uuid4()), thread_id=thread['id'], author_id=str(uuid4()), author_username='bob',
                   thread_title='Exported thread', body='A reply', created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())
    def respond(request):
        if 'cursor' not in request.url.params:
            return httpx.Response(200, json={'items': [comment], 'next_cursor': 'next-page'})
        return httpx.Response(200, json={'items': [thread], 'next_cursor': None})
    assert await rebuild(engine, respond) == {'thread': 1, 'comment': 1}
    docs = await documents(engine)
    assert set(docs) == {('thread', thread['id']), ('comment', comment['id'])}
    assert docs['comment', comment['id']].tags == 'python'
    assert docs['comment', comment['id']].author_username == 'bob'
    assert (await ledger(engine))[0].event_id == processed.event_id


async def test_export_failure_after_first_page_preserves_existing_index(database):
    engine, schema = database
    old = document()
    await save(engine, old)
    def respond(request):
        if 'cursor' not in request.url.params:
            return httpx.Response(200, json={'items': [thread_record()], 'next_cursor': 'next-page'})
        return httpx.Response(503)
    with pytest.raises(httpx.HTTPStatusError):
        await rebuild(engine, respond)
    assert set(await documents(engine)) == {('thread', str(old.source_id))}


async def test_orphan_comment_rejects_incomplete_export_and_rolls_back(database):
    engine, schema = database
    old = document()
    await save(engine, old)
    comment = dict(type='comment', id=str(uuid4()), thread_id=str(uuid4()), author_id=str(uuid4()), author_username='alice',
                   thread_title='Missing thread', body='Reply', created_at=datetime.now(timezone.utc).isoformat(), updated_at=datetime.now(timezone.utc).isoformat())
    with pytest.raises(ValueError, match='without a thread'):
        await rebuild(engine, lambda request: httpx.Response(200, json={'items': [comment], 'next_cursor': None}))
    assert set(await documents(engine)) == {('thread', str(old.source_id))}


async def test_empty_export_atomically_removes_obsolete_index(database):
    engine, schema = database
    await save(engine, document())
    assert await rebuild(engine, lambda request: httpx.Response(200, json={'items': [], 'next_cursor': None})) == {'thread': 0, 'comment': 0}
    assert not await documents(engine)


async def test_readers_keep_old_index_and_live_events_wait_until_commit(database, monkeypatch):
    engine, schema = database
    old = document()
    await save(engine, old)
    exported = thread_record()
    fetching, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def respond(request):
        fetching.set()
        await release.wait()
        return httpx.Response(200, json={'items': [exported], 'next_cursor': None})
    original_lock = index_events.lock_index
    async def tracked_lock(session):
        waiting.set()
        await original_lock(session)
    monkeypatch.setattr(index_events, 'lock_index', tracked_lock)
    async def live_event():
        async with AsyncSession(engine) as session:
            async with session.begin():
                await index_events.process_event(session, event('thread.updated', dict(thread_id=exported['id'], title='Live title', description='Live body', tags=['redis'])), 'stream:discussion')
    task = asyncio.create_task(rebuild(engine, respond))
    live = None
    try:
        async with asyncio.timeout(3):
            await fetching.wait()
        assert set(await documents(engine)) == {('thread', str(old.source_id))}
        live = asyncio.create_task(live_event())
        async with asyncio.timeout(3):
            await waiting.wait()
        assert not live.done()
        release.set()
        async with asyncio.timeout(3):
            await asyncio.gather(task, live)
        rebuilt = next(iter((await documents(engine)).values()))
        assert rebuilt.title == 'Live title'
        assert rebuilt.body == 'Live body'
    finally:
        for item in [task, live]:
            if item is not None:
                item.cancel()
        await asyncio.gather(*(item for item in [task, live] if item is not None), return_exceptions=True)
