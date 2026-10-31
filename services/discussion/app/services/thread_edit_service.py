import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.policy import can_modify
from app.domain.tags import normalize_and_validate_tags
from app.domain.validation import validate_thread_input
from app.models.outbox import Outbox
from app.models.tag import Tag
from app.models.thread import Thread
from app.models.thread_tag import ThreadTag


async def edit_thread(
    db: AsyncSession,
    thread_id: UUID,
    actor,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> tuple[Thread, list[str]] | None:
    try:
        result = await db.execute(
            select(Thread)
            .where(
                Thread.id == thread_id,
                Thread.deleted_at.is_(None),
            )
            .with_for_update()
        )
        thread = result.scalar_one_or_none()

        if thread is None:
            return None

        if not can_modify(actor, thread):
            raise PermissionError("You are not allowed to edit this thread.")

        new_title = title.strip() if title is not None else thread.title
        new_description = (
            description.strip()
            if description is not None
            else thread.description
        )

        validate_thread_input(new_title, new_description)

        if title is not None:
            thread.title = new_title

        if description is not None:
            thread.description = new_description

        if tags is None:
            tag_result = await db.execute(
                select(Tag.name)
                .join(ThreadTag, ThreadTag.tag_id == Tag.id)
                .where(ThreadTag.thread_id == thread.id)
                .order_by(Tag.name)
            )
            final_tags = list(tag_result.scalars().all())

        else:
            final_tags = normalize_and_validate_tags(tags)

            await db.execute(
                ThreadTag.__table__.delete().where(
                    ThreadTag.thread_id == thread.id
                )
            )

            if final_tags:
                tag_result = await db.execute(
                    select(Tag).where(Tag.name.in_(final_tags))
                )
                existing_tags = tag_result.scalars().all()
                tags_by_name = {
                    item.name: item for item in existing_tags
                }

                for tag_name in final_tags:
                    if tag_name not in tags_by_name:
                        tag = Tag(
                            id=uuid.uuid4(),
                            name=tag_name,
                        )
                        db.add(tag)
                        tags_by_name[tag_name] = tag

                await db.flush()

                for tag_name in final_tags:
                    db.add(
                        ThreadTag(
                            thread_id=thread.id,
                            tag_id=tags_by_name[tag_name].id,
                        )
                    )

        now = datetime.now(timezone.utc)
        thread.updated_at = now

        outbox_id = uuid.uuid4()

        db.add(
            Outbox(
                id=outbox_id,
                event_type="thread.updated",
                payload={
                    "event_id": str(outbox_id),
                    "type": "thread.updated",
                    "version": 1,
                    "occurred_at": now.isoformat(),
                    "producer": "discussion",
                    "payload": {
                        "thread_id": str(thread.id),
                        "title": thread.title,
                        "description": thread.description,
                        "tags": final_tags,
                        "updated_at": now.isoformat(),
                    },
                },
            )
        )

        # Moderator/admin edits of another user's thread are audited.
        if actor.role in ("moderator", "admin"):
            activity_id = uuid.uuid4()
            action = (
                "thread_edited_by_moderator"
                if actor.role == "moderator"
                else "thread_edited_by_admin"
            )

            db.add(
                Outbox(
                    id=activity_id,
                    event_type="activity.recorded",
                    payload={
                        "event_id": str(activity_id),
                        "type": "activity.recorded",
                        "version": 1,
                        "occurred_at": now.isoformat(),
                        "producer": "discussion",
                        "payload": {
                            "actor_id": str(actor.user_id),
                            "actor_role": actor.role,
                            "action": action,
                            "target_type": "thread",
                            "target_id": str(thread.id),
                            "metadata": {},
                            "occurred_at": now.isoformat(),
                        },
                    },
                )
            )

        await db.commit()
        await db.refresh(thread)

        return thread, final_tags

    except Exception:
        await db.rollback()
        raise