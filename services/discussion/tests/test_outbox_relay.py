import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError
from sqlalchemy.dialects import postgresql

from app.models.outbox import Outbox
from app.outbox import relay


def row(event_type="thread.created", legacy=False):
    event_id, thread_id = uuid4(), uuid4()
    envelope = {"event_id": str(event_id), "event_type" if legacy else "type": event_type,
                "version": 1, "producer": "discussion", "occurred_at": datetime.now(timezone.utc).isoformat(),
                "payload": {"thread_id": str(thread_id), "target_type": "thread", "like_count": 1}}
    return Outbox(id=event_id, event_type=event_type, payload=envelope, created_at=datetime.now(timezone.utc))


def session(rows):
    db = AsyncMock()
    db.begin = MagicMock(return_value=AsyncMock())
    result = MagicMock()
    result.all.return_value = rows
    db.scalars.return_value = result
    return db


@pytest.mark.parametrize("kind,channel,stream", [
    ("thread.created", "ws:global", True), ("thread.updated", "ws:global", True),
    ("thread.deleted", "ws:global", True), ("comment.created", "thread", True),
    ("comment.updated", "thread", True), ("comment.deleted", "thread", True),
    ("like.changed", "ws:global", False), ("report.created", None, True), ("activity.recorded", None, True),
])
async def test_fixed_destinations_and_unchanged_stable_envelope(kind, channel, stream):
    event = row(kind)
    redis = AsyncMock()
    await relay.publish_row(redis, event)
    if stream:
        args, kwargs = redis.xadd.call_args
        assert args[0] == "stream:discussion"
        assert json.loads(args[1]["envelope"]) == event.payload
        assert kwargs == {"maxlen": 100_000, "approximate": True}
    else:
        redis.xadd.assert_not_awaited()
    if channel:
        actual_channel, message = redis.publish.call_args.args
        assert actual_channel == (f"ws:thread:{event.payload['payload']['thread_id']}" if channel == "thread" else channel)
        assert json.loads(message) == {"type": "event", "event": kind, "thread_id": event.payload["payload"]["thread_id"], "data": event.payload["payload"]}
    else:
        redis.publish.assert_not_awaited()


async def test_comment_like_is_live_only_and_thread_scoped():
    event = row("like.changed")
    event.payload["payload"]["target_type"] = "comment"
    redis = AsyncMock()
    await relay.publish_row(redis, event)
    redis.xadd.assert_not_awaited()
    assert redis.publish.call_args.args[0] == f"ws:thread:{event.payload['payload']['thread_id']}"


async def test_legacy_report_envelope_is_normalized_without_mutating_stored_payload():
    event, redis = row("report.created", legacy=True), AsyncMock()
    await relay.publish_row(redis, event)
    envelope = json.loads(redis.xadd.call_args.args[1]["envelope"])
    assert envelope["type"] == "report.created" and "event_type" not in envelope
    assert "event_type" in event.payload and envelope["event_id"] == str(event.id)


@pytest.mark.parametrize("change", ["wrong_id", "wrong_type", "unknown_type", "invalid_thread", "invalid_target"])
async def test_invalid_rows_are_rejected_before_any_delivery(change):
    event, redis = row("like.changed"), AsyncMock()
    if change == "wrong_id": event.payload["event_id"] = str(uuid4())
    if change == "wrong_type": event.payload["type"] = "thread.created"
    if change == "unknown_type": event.event_type = event.payload["type"] = "unknown"
    if change == "invalid_thread": event.payload["payload"]["thread_id"] = "invalid"
    if change == "invalid_target": event.payload["payload"]["target_type"] = "user"
    with pytest.raises(ValueError): await relay.publish_row(redis, event)
    redis.xadd.assert_not_awaited()
    redis.publish.assert_not_awaited()


async def test_ordered_bounded_unpublished_query():
    db = session([])
    assert await relay.publish_pending_batch(db, AsyncMock(), 7) == 0
    sql = str(db.scalars.call_args.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "outbox.published_at IS NULL" in sql and "ORDER BY outbox.created_at, outbox.id" in sql and "LIMIT 7" in sql


async def test_rows_marked_published_only_after_both_destinations_complete():
    db, redis, order = session([row(), row()]), AsyncMock(), []
    async def stream(*args, **kwargs): order.append("stream")
    async def publish(*args, **kwargs): order.append("publish")
    async def update(*args, **kwargs): order.append("mark")
    redis.xadd.side_effect, redis.publish.side_effect, db.execute.side_effect = stream, publish, update
    assert await relay.publish_pending_batch(db, redis, 10) == 2
    assert order == ["stream", "publish", "mark"] * 2


@pytest.mark.parametrize("destination", ["xadd", "publish"])
async def test_delivery_failure_leaves_current_and_later_rows_unpublished(destination):
    db, redis = session([row(), row()]), AsyncMock()
    getattr(redis, destination).side_effect = ConnectionError("Unavailable")
    with pytest.raises(ConnectionError): await relay.publish_pending_batch(db, redis, 10)
    db.execute.assert_not_awaited()
    assert redis.xadd.await_count == 1


async def test_lifespan_cancels_relay_before_closing_redis(monkeypatch):
    from app import main
    redis, order, started = AsyncMock(), [], asyncio.Event()
    async def run():
        started.set()
        try: await asyncio.Future()
        finally: order.append("relay_stopped")
    async def close(): order.append("redis_closed")
    redis.aclose.side_effect = close
    monkeypatch.setattr(main, "get_redis_client", lambda: redis)
    monkeypatch.setattr(main, "run_outbox_relay", run)
    async with main.lifespan(main.app): await started.wait()
    assert order == ["relay_stopped", "redis_closed"]
