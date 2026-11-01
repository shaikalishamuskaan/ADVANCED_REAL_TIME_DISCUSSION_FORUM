from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Shared by live index writes and rebuild; released automatically on commit/rollback.
INDEX_LOCK_KEY = 0x534541524348


async def lock_index(session: AsyncSession):
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": INDEX_LOCK_KEY})
