import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProcessedEvent, SearchDocument
from app.services.index_events import process_event
from tests.test_database_integration import database

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get('RUN_SEARCH_INTEGRATION') != '1', reason='Set RUN_SEARCH_INTEGRATION=1; requires local PostgreSQL')]


def event(kind, payload):
    return {'event_id': str(uuid4()), 'type': kind, 'version': 1,
            'occurred_at': datetime.now(timezone.utc).isoformat(),
            'producer': 'identity' if kind.startswith('user.') else 'discussion', 'payload': payload}


def thread_created(thread_id=None, author_id=None):
    return event('thread.created', dict(thread_id=str(thread_id or uuid4()), author_id=str(author_id or uuid4()),
        author_username='alice', title='Original title', description='Thread body', tags=['python', 'redis'],
        created_at=datetime.now(timezone.utc).isoformat()))


def comment_created(thread, author_id=None):
    return event('comment.created', dict(comment_id=str(uuid4()), thread_id=thread['payload']['thread_id'],
        author_id=str(author_id or uuid4()), author_username='bob', body='A reply',
        created_at=datetime.now(timezone.utc).isoformat()))


async def apply(engine, envelope):
    stream = 'stream:identity' if envelope['type'].startswith('user.') else 'stream:discussion'
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            await process_event(session, envelope, stream)


async def documents(engine):
    async with AsyncSession(engine) as session:
        return {(doc.doc_type, str(doc.source_id)): doc for doc in (await session.scalars(select(SearchDocument))).all()}


async def ledger(engine):
    async with AsyncSession(engine) as session:
        return list((await session.scalars(select(ProcessedEvent))).all())


async def test_creates_thread_and_comment_from_event_data_only(database):
    engine, schema = database
    thread = thread_created()
    comment = comment_created(thread)
    await apply(engine, thread)
    await apply(engine, comment)
    docs = await documents(engine)
    t = docs['thread', thread['payload']['thread_id']]
    c = docs['comment', comment['payload']['comment_id']]
    assert t.title == t.thread_title == c.thread_title == 'Original title'
    assert t.body == 'Thread body' and c.body == 'A reply'
    assert c.title is None
    assert str(t.author_id) == thread['payload']['author_id']
    assert t.author_username == 'alice' and c.author_username == 'bob'
    assert t.tags == c.tags == 'python redis'
    assert t.created_at == datetime.fromisoformat(thread['payload']['created_at'])
    assert c.created_at == datetime.fromisoformat(comment['payload']['created_at'])
    assert len(await ledger(engine)) == 2


async def test_updates_preserve_metadata_and_propagate_thread_title(database):
    engine, schema = database
    thread = thread_created()
    comment = comment_created(thread)
    await apply(engine, thread)
    await apply(engine, comment)
    before = await documents(engine)
    changed = event('thread.updated', dict(thread_id=thread['payload']['thread_id'], title='New title', description='New body', tags=['fastapi']))
    await apply(engine, changed)
    await apply(engine, event('comment.updated', dict(thread_id=thread['payload']['thread_id'], comment_id=comment['payload']['comment_id'], body='Edited reply')))
    after = await documents(engine)
    for key, doc in after.items():
        assert doc.id == before[key].id
        assert doc.author_id == before[key].author_id
        assert doc.created_at == before[key].created_at
        assert doc.thread_title == 'New title'
        assert doc.tags == 'fastapi'
    assert after['thread', thread['payload']['thread_id']].body == 'New body'
    assert after['comment', comment['payload']['comment_id']].body == 'Edited reply'


async def test_comment_delete_and_thread_delete_keep_other_threads(database):
    engine, schema = database
    first, other = thread_created(), thread_created()
    comment, sibling = comment_created(first), comment_created(first)
    for envelope in [first, other, comment, sibling]:
        await apply(engine, envelope)
    await apply(engine, event('comment.deleted', {'comment_id': comment['payload']['comment_id']}))
    docs = await documents(engine)
    assert len(docs) == 3
    assert ('comment', comment['payload']['comment_id']) not in docs
    await apply(engine, event('thread.deleted', {'thread_id': first['payload']['thread_id']}))
    assert set(await documents(engine)) == {('thread', other['payload']['thread_id'])}


async def test_username_changes_all_matching_documents_but_disabled_does_not_remove_content(database):
    engine, schema = database
    author = uuid4()
    thread = thread_created(author_id=author)
    comment = comment_created(thread, author_id=author)
    other = thread_created()
    for envelope in [thread, comment, other]:
        await apply(engine, envelope)
    await apply(engine, event('user.username_changed', {'user_id': str(author), 'old_username': 'alice', 'new_username': 'renamed'}))
    await apply(engine, event('user.disabled', {'user_id': str(author)}))
    docs = await documents(engine)
    assert len(docs) == 3
    assert docs['thread', thread['payload']['thread_id']].author_username == 'renamed'
    assert docs['comment', comment['payload']['comment_id']].author_username == 'renamed'
    assert docs['thread', other['payload']['thread_id']].author_username == 'alice'


async def test_duplicate_event_does_not_overwrite_later_changes(database):
    engine, schema = database
    thread = thread_created()
    await apply(engine, thread)
    original_id = next(iter((await documents(engine)).values())).id
    changed = event('thread.updated', dict(thread_id=thread['payload']['thread_id'], title='New title', description='New body', tags=[]))
    await apply(engine, changed)
    await apply(engine, thread)
    await apply(engine, changed)
    docs = await documents(engine)
    assert len(docs) == 1
    assert next(iter(docs.values())).title == 'New title'
    assert next(iter(docs.values())).id == original_id
    assert len(await ledger(engine)) == 2


async def test_missing_thread_comment_is_retryable_without_a_false_dedup_record(database):
    engine, schema = database
    thread = thread_created()
    comment = comment_created(thread)
    with pytest.raises(ValueError, match='not indexed'):
        await apply(engine, comment)
    assert not await documents(engine)
    assert not await ledger(engine)
    await apply(engine, thread)
    await apply(engine, comment)
    assert len(await documents(engine)) == 2


async def test_missing_update_target_can_be_retried_after_create(database):
    engine, schema = database
    thread = thread_created()
    changed = event('thread.updated', dict(thread_id=thread['payload']['thread_id'], title='Changed', description='Changed body', tags=[]))
    with pytest.raises(ValueError, match='not indexed'):
        await apply(engine, changed)
    assert not await ledger(engine)
    await apply(engine, thread)
    await apply(engine, changed)
    assert next(iter((await documents(engine)).values())).title == 'Changed'


async def test_transaction_failure_rolls_back_index_and_dedup(database):
    engine, schema = database
    async with AsyncSession(engine) as session:
        with pytest.raises(RuntimeError):
            async with session.begin():
                await process_event(session, thread_created(), 'stream:discussion')
                raise RuntimeError('Simulated failure before commit')
    assert not await documents(engine)
    assert not await ledger(engine)


@pytest.mark.parametrize('change', [{'version': 2}, {'producer': 'identity'}, {'occurred_at': '2026-11-01T12:00:00'}])
async def test_invalid_envelope_does_not_modify_index(database, change):
    engine, schema = database
    envelope = thread_created()
    envelope.update(change)
    with pytest.raises(ValueError):
        await apply(engine, envelope)
    assert not await ledger(engine)
    assert not await documents(engine)

async def test_concurrent_duplicate_claim_is_atomic(database):
    import asyncio
    engine, schema = database
    envelope = thread_created()
    async with asyncio.timeout(3):
        await asyncio.gather(apply(engine, envelope), apply(engine, envelope))
    assert len(await documents(engine)) == 1
    assert len(await ledger(engine)) == 1


async def test_upsert_preserves_document_id_for_same_source(database):
    engine, schema = database
    envelope = thread_created()
    await apply(engine, envelope)
    first = next(iter((await documents(engine)).values())).id
    envelope['event_id'] = str(uuid4())
    await apply(engine, envelope)
    assert len(await documents(engine)) == 1
    assert next(iter((await documents(engine)).values())).id == first
    assert len(await ledger(engine)) == 2
