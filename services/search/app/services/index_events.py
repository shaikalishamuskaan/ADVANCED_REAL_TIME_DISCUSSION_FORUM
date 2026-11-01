from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProcessedEvent, SearchDocument

DISCUSSION_EVENTS = {"thread.created", "thread.updated", "thread.deleted", "comment.created", "comment.updated", "comment.deleted"}
CONSUMER = "search"


class Event(BaseModel):
    event_id: UUID
    type: str
    version: Literal[1]
    occurred_at: AwareDatetime
    producer: str
    payload: dict


class ThreadContent(BaseModel):
    thread_id: UUID
    title: str
    description: str
    tags: list[str]


class ThreadCreated(ThreadContent):
    author_id: UUID
    author_username: str
    created_at: AwareDatetime


class CommentContent(BaseModel):
    comment_id: UUID
    thread_id: UUID
    body: str


class CommentCreated(CommentContent):
    author_id: UUID
    author_username: str
    created_at: AwareDatetime


class UsernameChanged(BaseModel):
    user_id: UUID
    new_username: str


async def upsert_document(session: AsyncSession, values: dict):
    statement = insert(SearchDocument).values(id=uuid4(), **values)
    await session.execute(statement.on_conflict_do_update(
        constraint="uq_search_document_type_source",
        set_={key: getattr(statement.excluded, key) for key in values if key not in {"doc_type", "source_id"}},
    ))


async def require_document(session, doc_type, source_id):
    document = await session.scalar(select(SearchDocument).where(
        SearchDocument.doc_type == doc_type, SearchDocument.source_id == source_id,
    ))
    if document is None:
        raise ValueError("Search document is not indexed yet; event must be retried")
    return document


async def process_event(session: AsyncSession, envelope: dict, stream: str):
    event = Event.model_validate(envelope)
    if stream == "stream:discussion":
        if event.type not in DISCUSSION_EVENTS:
            return
        producer = "discussion"
    elif stream == "stream:identity":
        if event.type != "user.username_changed":
            return
        producer = "identity"
    else:
        raise ValueError("Unknown Search event stream")
    if event.producer != producer:
        raise ValueError("Event producer does not match stream")
    claim = await session.execute(insert(ProcessedEvent).values(
        event_id=event.event_id, consumer=CONSUMER,
    ).on_conflict_do_nothing(index_elements=["event_id", "consumer"]).returning(ProcessedEvent.event_id))
    if claim.scalar_one_or_none() is None:
        return

    payload = event.payload
    if event.type == "thread.created":
        data = ThreadCreated.model_validate(payload)
        await upsert_document(session, dict(
            doc_type="thread", source_id=data.thread_id, thread_id=data.thread_id,
            author_id=data.author_id, author_username=data.author_username,
            thread_title=data.title, title=data.title, body=data.description,
            tags=" ".join(data.tags), created_at=data.created_at,
        ))
    elif event.type == "thread.updated":
        data = ThreadContent.model_validate(payload)
        await require_document(session, "thread", data.thread_id)
        await session.execute(update(SearchDocument).where(
            SearchDocument.doc_type == "thread", SearchDocument.source_id == data.thread_id,
        ).values(title=data.title, thread_title=data.title, body=data.description, tags=" ".join(data.tags)))
        await session.execute(update(SearchDocument).where(
            SearchDocument.doc_type == "comment", SearchDocument.thread_id == data.thread_id,
        ).values(thread_title=data.title, tags=" ".join(data.tags)))
    elif event.type == "comment.created":
        data = CommentCreated.model_validate(payload)
        thread = await require_document(session, "thread", data.thread_id)
        await upsert_document(session, dict(
            doc_type="comment", source_id=data.comment_id, thread_id=data.thread_id,
            author_id=data.author_id, author_username=data.author_username,
            thread_title=thread.title, title=None, body=data.body,
            tags=thread.tags, created_at=data.created_at,
        ))
    elif event.type == "comment.updated":
        data = CommentContent.model_validate(payload)
        comment = await require_document(session, "comment", data.comment_id)
        if comment.thread_id != data.thread_id:
            raise ValueError("Comment update does not match its indexed thread")
        await session.execute(update(SearchDocument).where(
            SearchDocument.doc_type == "comment", SearchDocument.source_id == data.comment_id,
            SearchDocument.thread_id == data.thread_id,
        ).values(body=data.body))
    elif event.type == "thread.deleted":
        thread_id = UUID(str(payload["thread_id"]))
        await session.execute(delete(SearchDocument).where(SearchDocument.thread_id == thread_id))
    elif event.type == "comment.deleted":
        comment_id = UUID(str(payload["comment_id"]))
        await session.execute(delete(SearchDocument).where(
            SearchDocument.doc_type == "comment", SearchDocument.source_id == comment_id,
        ))
    else:
        data = UsernameChanged.model_validate(payload)
        await session.execute(update(SearchDocument).where(
            SearchDocument.author_id == data.user_id,
        ).values(author_username=data.new_username))
