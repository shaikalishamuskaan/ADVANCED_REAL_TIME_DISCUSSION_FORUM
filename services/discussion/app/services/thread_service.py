import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tags import normalize_and_validate_tags
from app.domain.validation import validate_thread_input
from app.models.outbox import Outbox
from app.models.tag import Tag
from app.models.thread import Thread
from app.models.thread_tag import ThreadTag


async def create_thread(
    db: AsyncSession,
    author_id: UUID,
    author_username:str,
    title: str,
    description: str,
    tags: list[str],
) -> Thread:
    try:
        # 1. Validate thread fields and normalize tags.
        validate_thread_input(title, description)
        normalized_tags = normalize_and_validate_tags(tags)

        # 2. Find tags that already exist.
        result = await db.execute(
            select(Tag).where(Tag.name.in_(normalized_tags))
        )
        existing_tags = result.scalars().all()
        tags_by_name = {tag.name: tag for tag in existing_tags}

        # 3. Create tags that do not exist yet.
        for tag_name in normalized_tags:
            if tag_name not in tags_by_name:
                tag = Tag(
                    id=uuid.uuid4(),
                    name=tag_name,
                )
                db.add(tag)
                tags_by_name[tag_name] = tag

        # Flush makes the new Tag rows available in the transaction.
        await db.flush()

        # 4. Create the thread.
        now = datetime.now(timezone.utc)

        thread = Thread(
            id=uuid.uuid4(),
            author_id=author_id,
            title=title.strip(),
            description=description.strip(),
            like_count=0,
            comment_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(thread)

        # 5. Connect each tag to the thread.
        for tag_name in normalized_tags:
            db.add(
                ThreadTag(
                    thread_id=thread.id,
                    tag_id=tags_by_name[tag_name].id,
                )
            )

        # 6. Create the transactional Outbox event.
        outbox_id = uuid.uuid4()

        db.add(
            Outbox(
                id=outbox_id,
                event_type="thread.created",
                payload={
                    "event_id": str(outbox_id),
                    "type": "thread.created",
                    "version": 1,
                    "occurred_at": now.isoformat(),
                    "producer": "discussion",
                    "payload": {
                        "thread_id": str(thread.id),
                        "author_id": str(author_id),
                        "author_username": author_username,
                        "title": thread.title,
                        "description": thread.description,
                        "tags": normalized_tags,
                        "created_at": now.isoformat(),
                    },
                },
            )
        )

        # 7. Commit thread, tags, relationships and event together.
        await db.commit()
        await db.refresh(thread)

        return thread

    except Exception:
        await db.rollback()
        raise