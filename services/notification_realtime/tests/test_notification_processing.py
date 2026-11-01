import asyncio
import os
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import event as sqlalchemy_event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, Outbox, ProcessedEvent
from app.notify.services import event_processor as processor
from tests.test_outbox_integration import infrastructure


def make_event(event_type='comment.created'):
    return {
        'event_id': str(uuid4()), 'type': event_type, 'version': 1,
        'occurred_at': '2026-11-01T12:00:00Z', 'producer': 'discussion',
        'payload': {
            'thread_id': str(uuid4()), 'comment_id': str(uuid4()),
            'author_id': str(uuid4()), 'thread_author_id': str(uuid4()),
            'parent_id': None, 'parent_author_id': None,
            'body': '', 'description': '',
        },
    }


def session_with_results(*values):
    session = AsyncMock()
    session.add = MagicMock()
    session.execute.side_effect = [MagicMock(scalar_one_or_none=MagicMock(return_value=value)) for value in values]
    return session


@pytest.mark.asyncio
async def test_duplicate_claim_skips_identity_and_notification_work(monkeypatch):
    resolver = AsyncMock()
    monkeypatch.setattr(processor, 'resolve_usernames', resolver)
    session = session_with_results(None)
    await processor.process_event(session, make_event())
    assert session.execute.await_count == 1
    session.add.assert_not_called()
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_event_has_no_effect():
    session = AsyncMock()
    await processor.process_event(session, make_event('thread.updated'))
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_mentions_skips_identity(monkeypatch):
    resolver = AsyncMock()
    monkeypatch.setattr(processor, 'resolve_usernames', resolver)
    event = make_event()
    session = session_with_results(uuid4(), uuid4())
    await processor.process_event(session, event)
    resolver.assert_not_awaited()
    assert session.add.call_args.args[0].event_type == 'notification.created'


@pytest.mark.asyncio
async def test_existing_notification_does_not_create_another_live_outbox():
    session = session_with_results(uuid4(), None)
    await processor.process_event(session, make_event())
    session.add.assert_not_called()


async def process(engine, event):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            await processor.process_event(session, event)


async def rows(engine, model):
    async with AsyncSession(engine) as session:
        return list((await session.scalars(select(model))).all())


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('RUN_OUTBOX_INTEGRATION') != '1', reason='Set RUN_OUTBOX_INTEGRATION=1; requires local PostgreSQL and Redis')
class TestNotificationProcessingIntegration:
    @pytest.mark.parametrize('nested', [False, True])
    async def test_reply_recipient_and_live_payload(self, infrastructure, nested):
        engine, redis = infrastructure
        event = make_event()
        payload = event['payload']
        if nested:
            payload.update(parent_id=str(uuid4()), parent_author_id=str(uuid4()))
        await process(engine, event)
        notifications = await rows(engine, Notification)
        outbox = await rows(engine, Outbox)
        ledger = await rows(engine, ProcessedEvent)
        assert len(notifications) == len(outbox) == len(ledger) == 1
        note = notifications[0]
        recipient = payload['parent_author_id'] if nested else payload['thread_author_id']
        assert str(note.recipient_id) == recipient
        assert note.type == ('reply_comment' if nested else 'reply_thread')
        assert str(note.source_event_id) == event['event_id']
        assert ledger[0].processed_at is not None
        assert outbox[0].payload == {
            'target': f'ws:user:{recipient}',
            'event': {'type': 'notification', 'data': {
                'id': str(note.id), 'type': note.type,
                'actor_id': payload['author_id'], 'thread_id': payload['thread_id'],
                'comment_id': payload['comment_id'],
            }},
        }

    async def test_mentions_override_reply_and_exclude_actor_and_unknown_names(self, infrastructure, monkeypatch):
        engine, redis = infrastructure
        event = make_event()
        event['payload']['body'] = '@sara @ali @missing'
        resolver = AsyncMock(return_value={
            'sara': {'id': event['payload']['thread_author_id']},
            'ali': {'id': event['payload']['author_id']},
        })
        monkeypatch.setattr(processor, 'resolve_usernames', resolver)
        await process(engine, event)
        notifications = await rows(engine, Notification)
        assert len(notifications) == 1
        assert notifications[0].type == 'mention'
        assert str(notifications[0].recipient_id) == event['payload']['thread_author_id']
        resolver.assert_awaited_once_with(['sara', 'ali', 'missing'])

    async def test_thread_created_only_notifies_mentions(self, infrastructure, monkeypatch):
        engine, redis = infrastructure
        event = make_event('thread.created')
        event['payload']['description'] = '@sara @ali'
        recipient = str(uuid4())
        monkeypatch.setattr(processor, 'resolve_usernames', AsyncMock(return_value={
            'sara': {'id': recipient}, 'ali': {'id': event['payload']['author_id']},
        }))
        await process(engine, event)
        notifications = await rows(engine, Notification)
        assert len(notifications) == 1
        assert str(notifications[0].recipient_id) == recipient
        assert notifications[0].type == 'mention'
        assert notifications[0].comment_id is None

    @pytest.mark.parametrize('event_type', ['comment.created', 'thread.created'])
    async def test_no_recipients_still_records_processed_event(self, infrastructure, event_type):
        engine, redis = infrastructure
        event = make_event(event_type)
        event['payload']['thread_author_id'] = event['payload']['author_id']
        await process(engine, event)
        await process(engine, event)
        assert not await rows(engine, Notification)
        assert not await rows(engine, Outbox)
        assert len(await rows(engine, ProcessedEvent)) == 1

    async def test_sequential_duplicate_skips_identity(self, infrastructure, monkeypatch):
        engine, redis = infrastructure
        event = make_event()
        event['payload']['body'] = '@sara'
        resolver = AsyncMock(return_value={'sara': {'id': event['payload']['thread_author_id']}})
        monkeypatch.setattr(processor, 'resolve_usernames', resolver)
        await process(engine, event)
        resolver.side_effect = RuntimeError('Identity should not be called on redelivery')
        await process(engine, event)
        assert resolver.await_count == 1
        assert len(await rows(engine, Notification)) == 1
        assert len(await rows(engine, Outbox)) == 1
        assert len(await rows(engine, ProcessedEvent)) == 1

    @pytest.mark.parametrize('winner_fails', [False, True])
    async def test_concurrent_duplicates_claim_event_once(self, infrastructure, monkeypatch, winner_fails):
        engine, redis = infrastructure
        event = make_event()
        event['payload']['body'] = '@sara'
        entered, release, second_insert = asyncio.Event(), asyncio.Event(), asyncio.Event()
        insert_count = 0
        def track_insert(connection, cursor, statement, parameters, context, executemany):
            nonlocal insert_count
            if 'INSERT INTO' in statement and 'processed_event' in statement:
                insert_count += 1
                if insert_count == 2:
                    second_insert.set()
        sqlalchemy_event.listen(engine.sync_engine, 'before_cursor_execute', track_insert)
        async def resolve(names):
            entered.set()
            await release.wait()
            if winner_fails and resolver.await_count == 1:
                raise RuntimeError('First worker failed before commit')
            return {'sara': {'id': event['payload']['thread_author_id']}}
        resolver = AsyncMock(side_effect=resolve)
        monkeypatch.setattr(processor, 'resolve_usernames', resolver)
        tasks = [asyncio.create_task(process(engine, event))]
        try:
            async with asyncio.timeout(3):
                await entered.wait()
            tasks.append(asyncio.create_task(process(engine, event)))
            async with asyncio.timeout(3):
                await second_insert.wait()
            assert not tasks[1].done()
            release.set()
            async with asyncio.timeout(3):
                results = await asyncio.gather(*tasks, return_exceptions=True)
            if winner_fails:
                assert isinstance(results[0], RuntimeError)
                assert results[1] is None
            else:
                assert results == [None, None]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            sqlalchemy_event.remove(engine.sync_engine, 'before_cursor_execute', track_insert)
        assert resolver.await_count == (2 if winner_fails else 1)
        assert len(await rows(engine, Notification)) == 1
        assert len(await rows(engine, Outbox)) == 1
        assert len(await rows(engine, ProcessedEvent)) == 1

    @pytest.mark.parametrize('failure_point', ['identity', 'outbox_flush'])
    async def test_failure_rolls_back_claim_notifications_and_outbox(self, infrastructure, monkeypatch, failure_point):
        engine, redis = infrastructure
        event = make_event()
        if failure_point == 'identity':
            event['payload']['body'] = '@sara'
            resolver = AsyncMock(side_effect=RuntimeError('Identity unavailable'))
            monkeypatch.setattr(processor, 'resolve_usernames', resolver)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if failure_point == 'outbox_flush':
                monkeypatch.setattr(session, 'flush', AsyncMock(side_effect=SQLAlchemyError('Flush failed')))
            with pytest.raises((RuntimeError, SQLAlchemyError)):
                async with session.begin():
                    await processor.process_event(session, event)
        assert not await rows(engine, Notification)
        assert not await rows(engine, Outbox)
        assert not await rows(engine, ProcessedEvent)
        if failure_point == 'identity':
            resolver.side_effect = None
            resolver.return_value = {}
        await process(engine, event)
        assert len(await rows(engine, Notification)) == 1
        assert len(await rows(engine, Outbox)) == 1
        assert len(await rows(engine, ProcessedEvent)) == 1

    async def test_replay_after_ledger_retention_does_not_duplicate_notifications(self, infrastructure):
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update
        from app.notify.workers.cleanup import cleanup_processed_events
        engine, redis = infrastructure
        event = make_event()
        await process(engine, event)
        async with AsyncSession(engine) as session:
            async with session.begin():
                await session.execute(update(ProcessedEvent).values(processed_at=datetime.now(timezone.utc) - timedelta(days=15)))
                assert await cleanup_processed_events(session) == 1
        await process(engine, event)
        assert len(await rows(engine, Notification)) == 1
        assert len(await rows(engine, Outbox)) == 1
        assert len(await rows(engine, ProcessedEvent)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('commit_failure', [False, True])
async def test_stream_ack_happens_only_after_successful_commit(monkeypatch, commit_failure):
    import json
    from app.notify.workers import consumer
    order = []
    session = AsyncMock()
    transaction = AsyncMock()
    session.begin = MagicMock(return_value=transaction)
    async def exit_transaction(*args):
        if commit_failure:
            raise SQLAlchemyError('Commit failed')
        order.append('commit')
    transaction.__aexit__.side_effect = exit_transaction
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    monkeypatch.setattr(consumer, 'AsyncSessionLocal', MagicMock(return_value=session_context))
    async def processed(*args): order.append('process')
    monkeypatch.setattr(consumer, 'process_event', AsyncMock(side_effect=processed))
    redis = AsyncMock()
    redis.xpending_range.return_value = [{'times_delivered': 1}]
    async def acked(*args): order.append('ack')
    redis.xack.side_effect = acked
    await consumer.handle_entry(redis, '1-0', {'envelope': json.dumps(make_event())})
    if commit_failure:
        assert order == ['process']
        redis.xack.assert_not_awaited()
    else:
        assert order == ['process', 'commit', 'ack']
        redis.xack.assert_awaited_once_with('stream:discussion', 'notify', '1-0')
