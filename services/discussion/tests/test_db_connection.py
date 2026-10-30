import pytest
from sqlalchemy import text

from app.core.database import engine


@pytest.mark.asyncio
async def test_connection():
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT 1"))

    assert result.scalar() == 1