from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag
from app.models.thread_tag import ThreadTag


async def delete_tag(
    db: AsyncSession,
    tag_id: UUID,
) -> bool:
    try:
        result = await db.execute(
            select(Tag).where(Tag.id == tag_id)
        )
        tag = result.scalar_one_or_none()

        if tag is None:
            return False

        await db.execute(
            delete(ThreadTag).where(
                ThreadTag.tag_id == tag_id
            )
        )

        await db.delete(tag)
        await db.commit()

        return True

    except Exception:
        await db.rollback()
        raise