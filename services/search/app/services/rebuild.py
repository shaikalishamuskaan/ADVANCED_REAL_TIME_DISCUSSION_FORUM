from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.clients.discussion_export import DiscussionExportClient, ExportThread
from app.models import SearchDocument
from app.services.index_lock import lock_index


async def rebuild_index(session: AsyncSession, export: DiscussionExportClient) -> dict[str, int]:
    counts = {"thread": 0, "comment": 0}
    async with session.begin():
        # Old documents remain visible to readers until this entire transaction
        # commits. Live index writes wait on the same lock; their stream ACKs wait too.
        await lock_index(session)
        await session.execute(delete(SearchDocument))
        async for page in export.pages():
            values = []
            for record in page.items:
                is_thread = isinstance(record, ExportThread)
                values.append(dict(
                    doc_type=record.type, source_id=record.id,
                    thread_id=record.id if is_thread else record.thread_id,
                    author_id=record.author_id, author_username=record.author_username,
                    title=record.title if is_thread else None,
                    thread_title=record.title if is_thread else record.thread_title,
                    body=record.description if is_thread else record.body,
                    tags=" ".join(record.tags) if is_thread else "",
                    created_at=record.created_at,
                ))
                counts[record.type] += 1
            if values:
                await session.execute(insert(SearchDocument), values)
        thread = aliased(SearchDocument)
        comment = aliased(SearchDocument)
        parent_exists = exists(select(thread.id).where(thread.doc_type == "thread", thread.source_id == comment.thread_id))
        orphan = await session.scalar(select(comment.id).where(comment.doc_type == "comment", ~parent_exists).limit(1))
        if orphan is not None:
            raise ValueError("Discussion export has comments without a thread")
        # Export is newest-first, so comments can arrive before their thread.
        parent_tags = select(thread.tags).where(thread.doc_type == "thread", thread.source_id == SearchDocument.thread_id).scalar_subquery()
        parent_title = select(thread.title).where(thread.doc_type == "thread", thread.source_id == SearchDocument.thread_id).scalar_subquery()
        await session.execute(update(SearchDocument).where(SearchDocument.doc_type == "comment").values(tags=parent_tags, thread_title=parent_title))
        # Preserve the processed-event ledger and Redis group positions: queued
        # events resume after the rebuild and acknowledged duplicates still skip.
    return counts
