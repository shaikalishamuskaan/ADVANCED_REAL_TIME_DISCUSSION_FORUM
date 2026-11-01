import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import get_settings
from app.core.redis import close_redis_client, get_redis_client
from app.models import ProcessedEvent, SearchDocument

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.environ.get("RUN_SEARCH_INTEGRATION") != "1", reason="Set RUN_SEARCH_INTEGRATION=1; requires local PostgreSQL and Redis"),
]


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/81a3f92bd706_create_search_tables.py"
    spec = importlib.util.spec_from_file_location("search_initial_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest_asyncio.fixture
async def database():
    schema = f"test_search_{uuid4().hex}"
    engine = create_async_engine(get_settings().DATABASE_URL, execution_options={"schema_translate_map": {None: schema}})
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            def upgrade(sync):
                quoted = sync.dialect.identifier_preparer.quote(schema)
                sync.execute(text(f"SET LOCAL search_path TO {quoted}"))
                with Operations.context(MigrationContext.configure(sync)):
                    migration().upgrade()
            await connection.run_sync(upgrade)
        created = True
        yield engine, schema
    finally:
        if created:
            async with engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


def document(**overrides):
    values = dict(doc_type="thread", source_id=uuid4(), thread_id=uuid4(), author_id=uuid4(),
                  author_username="alice", thread_title="A thread", title="A thread", body="Example body", tags="python redis",
                  created_at=datetime.now(timezone.utc))
    values.update(overrides)
    return SearchDocument(**values)


async def save(engine, *records):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add_all(records)


async def test_migration_creates_exact_lld_tables_and_can_downgrade(database):
    engine, schema = database
    async with engine.begin() as connection:
        def check(sync):
            inspector = inspect(sync)
            assert set(inspector.get_table_names(schema=schema)) == {"search_document", "processed_event"}
            assert {col["name"] for col in inspector.get_columns("search_document", schema=schema)} == {
                "id", "doc_type", "source_id", "thread_id", "author_id", "author_username", "thread_title", "title", "body", "tags", "created_at",
            }
            assert set(inspector.get_pk_constraint("processed_event", schema=schema)["constrained_columns"]) == {"event_id", "consumer"}
            quoted = sync.dialect.identifier_preparer.quote(schema)
            sync.execute(text(f"SET LOCAL search_path TO {quoted}"))
            with Operations.context(MigrationContext.configure(sync)):
                migration().downgrade()
                assert not inspect(sync).get_table_names(schema=schema)
                migration().upgrade()
        await connection.run_sync(check)


async def test_document_persists_event_fields_and_optional_comment_title(database):
    engine, schema = database
    record = document(doc_type="comment", title=None, body="Unicode reply: caf?")
    await save(engine, record)
    async with AsyncSession(engine) as session:
        saved = await session.get(SearchDocument, record.id)
        assert saved.title is None
        assert saved.body == "Unicode reply: caf?"
        assert saved.created_at.tzinfo is not None
        assert saved.author_username == "alice"


async def test_document_upsert_key_rejects_duplicates_but_allows_distinct_types(database):
    engine, schema = database
    source = uuid4()
    await save(engine, document(source_id=source), document(source_id=source, doc_type="comment", title=None))
    with pytest.raises(IntegrityError):
        await save(engine, document(source_id=source))
    async with AsyncSession(engine) as session:
        assert len((await session.scalars(select(SearchDocument))).all()) == 2


async def test_invalid_document_type_is_rejected(database):
    engine, schema = database
    with pytest.raises(IntegrityError):
        await save(engine, document(doc_type="unknown"))


async def test_processed_event_is_unique_per_consumer(database):
    engine, schema = database
    event = uuid4()
    await save(engine, ProcessedEvent(event_id=event, consumer="search"), ProcessedEvent(event_id=event, consumer="other-consumer"))
    with pytest.raises(IntegrityError):
        await save(engine, ProcessedEvent(event_id=event, consumer="search"))


async def test_database_transaction_rolls_back_documents_and_ledger(database):
    engine, schema = database
    record = document()
    event = ProcessedEvent(event_id=uuid4(), consumer="search")
    async with AsyncSession(engine) as session:
        with pytest.raises(RuntimeError):
            async with session.begin():
                session.add_all([record, event])
                await session.flush()
                raise RuntimeError("Simulated event processing failure")
    async with AsyncSession(engine) as session:
        assert not (await session.scalars(select(SearchDocument))).all()
        assert not (await session.scalars(select(ProcessedEvent))).all()


async def test_local_redis_connection():
    try:
        assert await get_redis_client().ping()
    finally:
        await close_redis_client()
