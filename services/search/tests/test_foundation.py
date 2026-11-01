import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import main
from app.core.config import SERVICE_ROOT, Settings


@pytest.mark.asyncio
async def test_health_endpoint():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "search"}


def test_settings_use_search_service_env_and_existing_jwt_defaults():
    settings = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://test:test@localhost/search_db")
    assert SERVICE_ROOT.name == "search"
    assert settings.JWT_ALGORITHM == "RS256"
    assert settings.JWT_ISSUER == "identity"
    assert settings.JWT_AUDIENCE == "forum"
    assert settings.REDIS_URL == "redis://localhost:6380/0"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "database", "redis"])
async def test_lifespan_checks_dependencies_and_cleans_up(monkeypatch, failure):
    connection = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = MagicMock()
    engine.connect.return_value = context
    engine.dispose = AsyncMock()
    redis = AsyncMock()
    closed = AsyncMock()
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "get_redis_client", lambda: redis)
    monkeypatch.setattr(main, "close_redis_client", closed)
    started, stopped = asyncio.Event(), asyncio.Event()
    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr(main, "consume_forever", worker)
    if failure == "database":
        connection.execute.side_effect = SQLAlchemyError("Unavailable")
    elif failure == "redis":
        redis.ping.side_effect = ConnectionError("Unavailable")
    if failure:
        with pytest.raises((SQLAlchemyError, ConnectionError)):
            async with main.lifespan(main.app):
                pytest.fail("Startup must fail when a required dependency is down")
    else:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
            assert started.is_set()
            redis.ping.assert_awaited_once()
            assert str(connection.execute.call_args.args[0]) == "SELECT 1"
    closed.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    assert stopped.is_set() is (failure is None)
