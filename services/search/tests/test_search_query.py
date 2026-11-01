import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cursor import decode_cursor, encode_cursor
from app.schemas.search import SearchQuery
from app.services.search_query import escape_like, make_snippet, search_documents
from tests.test_database_integration import database, document, save


@pytest.mark.parametrize('q', ['', 'a', ' a ', ' '*10, 'x'*101])
def test_invalid_query(q):
    with pytest.raises(ValidationError):
        SearchQuery(q=q)


def test_query_is_trimmed_and_tag_normalized():
    query = SearchQuery(q='  token  ', tag=' Python ')
    assert query.q == 'token'
    assert query.tag == 'python'
    assert query.limit == 20
    assert SearchQuery(q='token', tag='').tag is None


@pytest.mark.parametrize('values', [{'type': 'unknown'}, {'limit': 0}, {'limit': 51}, {'tag': 'bad tag'}])
def test_invalid_filters(values):
    with pytest.raises(ValidationError):
        SearchQuery(q='token', **values)


def test_like_escaping():
    assert escape_like(r'50%_path\name') == r'50\%\_path\\name'


def test_snippet_has_eighty_characters_context_and_is_plain_text():
    body = 'a'*100 + '<b>Token</b>' + 'z'*100
    assert make_snippet(body, 'token') == '...' + body[23:188] + '...'
    assert make_snippet('no match here', 'token') == 'no match here'


def test_cursor_round_trip():
    created = datetime.now(timezone.utc)
    ident = uuid4()
    cursor = encode_cursor(created, ident)
    assert decode_cursor(cursor) == (created, ident)
    assert decode_cursor(cursor.rstrip('=')) == (created, ident)


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get('RUN_SEARCH_INTEGRATION') != '1', reason='Set RUN_SEARCH_INTEGRATION=1; requires local PostgreSQL')
class TestSearchQueryIntegration:
    async def test_matches_title_body_and_tags_with_type_filter(self, database):
        engine, schema = database
        title = document(title='Refresh TOKEN rotation', body='Other text', tags='python')
        body = document(doc_type='comment', title=None, body='A token reply', tags='')
        tag = document(title='Other title', body='Other text', tags='token')
        unrelated = document(title='Unrelated', body='Other text', tags='python')
        await save(engine, title, body, tag, unrelated)
        async with AsyncSession(engine) as session:
            result = await search_documents(session, SearchQuery(q='ToKeN'))
            assert {item.id for item in result.items} == {title.source_id, body.source_id, tag.source_id}
            comments = await search_documents(session, SearchQuery(q='token', type='comment'))
            assert [item.id for item in comments.items] == [body.source_id]
            assert comments.items[0].title is None
            threads = await search_documents(session, SearchQuery(q='token', type='thread'))
            assert {item.id for item in threads.items} == {title.source_id, tag.source_id}

    @pytest.mark.parametrize('literal', ['50%', 'foo_bar', r'path\name', "a' OR '1'='1"])
    async def test_wildcards_and_sql_are_literal_search_text(self, database, literal):
        engine, schema = database
        matching = document(title='Other', body=f'Exact {literal} text', tags='')
        other = document(title='Other', body='50X fooXbar pathXname ordinary', tags='')
        await save(engine, matching, other)
        async with AsyncSession(engine) as session:
            result = await search_documents(session, SearchQuery(q=literal))
        assert [item.id for item in result.items] == [matching.source_id]

    async def test_tag_filter_matches_whole_normalized_tag(self, database):
        engine, schema = database
        exact = document(body='token', tags='python foo_bar')
        partial = document(body='token', tags='pythonic fooXbar')
        await save(engine, exact, partial)
        async with AsyncSession(engine) as session:
            for tag in [' PYTHON ', 'foo_bar']:
                result = await search_documents(session, SearchQuery(q='token', tag=tag))
                assert [item.id for item in result.items] == [exact.source_id]

    async def test_cursor_paginates_tied_times_by_internal_id_and_returns_source_ids(self, database):
        engine, schema = database
        now = datetime.now(timezone.utc)
        docs = [document(id=UUID(int=index), title='token', created_at=now) for index in range(1, 6)]
        await save(engine, *docs)
        received, cursor = [], None
        async with AsyncSession(engine) as session:
            while True:
                result = await search_documents(session, SearchQuery(q='token', limit=2, cursor=cursor))
                received.extend(item.id for item in result.items)
                cursor = result.next_cursor
                if cursor is None:
                    break
        assert received == [doc.source_id for doc in reversed(docs)]

    async def test_default_and_maximum_page_size_and_empty_results(self, database):
        engine, schema = database
        await save(engine, *(document(body='token') for _ in range(25)))
        async with AsyncSession(engine) as session:
            default = await search_documents(session, SearchQuery(q='token'))
            assert len(default.items) == 20
            assert default.next_cursor is not None
            maximum = await search_documents(session, SearchQuery(q='token', limit=50))
            assert len(maximum.items) == 25
            assert maximum.next_cursor is None
            empty = await search_documents(session, SearchQuery(q='no-match'))
            assert empty.items == [] and empty.next_cursor is None
