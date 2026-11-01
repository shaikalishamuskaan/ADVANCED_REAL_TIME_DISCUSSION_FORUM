from fastapi import HTTPException
from sqlalchemy import literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.cursor import decode_cursor, encode_cursor
from app.models.search_document import SearchDocument
from app.schemas.search import SearchItem, SearchQuery, SearchResponse


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def make_snippet(body: str, query: str) -> str:
    match = body.lower().find(query.lower())
    if match < 0:
        start, end = 0, min(len(body), 160)
    else:
        start, end = max(0, match - 80), min(len(body), match + len(query) + 80)
    return ("..." if start else "") + body[start:end] + ("..." if end < len(body) else "")


async def search_documents(session: AsyncSession, query: SearchQuery) -> SearchResponse:
    pattern = f"%{escape_like(query.q)}%"
    statement = select(SearchDocument).where(or_(
        SearchDocument.title.ilike(pattern, escape="\\"),
        SearchDocument.body.ilike(pattern, escape="\\"),
        SearchDocument.tags.ilike(pattern, escape="\\"),
    ))
    if query.type != "all":
        statement = statement.where(SearchDocument.doc_type == query.type)
    if query.tag:
        padded_tags = literal(" ") + SearchDocument.tags + literal(" ")
        statement = statement.where(padded_tags.ilike(f"% {escape_like(query.tag)} %", escape="\\"))
    if query.cursor:
        try:
            created_at, document_id = decode_cursor(query.cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": {
                "code": "invalid_cursor", "message": "Invalid cursor", "details": {},
            }})
        statement = statement.where(tuple_(SearchDocument.created_at, SearchDocument.id) < tuple_(created_at, document_id))
    statement = statement.order_by(SearchDocument.created_at.desc(), SearchDocument.id.desc()).limit(query.limit + 1)
    documents = list((await session.scalars(statement)).all())
    more = len(documents) > query.limit
    documents = documents[:query.limit]
    next_cursor = encode_cursor(documents[-1].created_at, documents[-1].id) if more else None
    return SearchResponse(items=[SearchItem(
        type=doc.doc_type, id=doc.source_id, thread_id=doc.thread_id,
        title=doc.title, thread_title=doc.thread_title,
        snippet=make_snippet(doc.body, query.q), author_username=doc.author_username,
        created_at=doc.created_at,
    ) for doc in documents], next_cursor=next_cursor)
