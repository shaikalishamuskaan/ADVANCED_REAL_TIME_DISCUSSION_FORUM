import json

import httpx
import pytest

from app.main import app
from forum_logging import JsonFormatter


@pytest.mark.asyncio
async def test_health_request_has_safe_correlated_log(caplog):
    identity = "11111111222243338444555555555555"
    with caplog.at_level("INFO", logger="forum.requests"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            response = await client.get("/health?password=SECRET",headers={"X-Request-ID":identity,"Authorization":"Bearer SECRET"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == identity
    record, = [item for item in caplog.records if item.name == "forum.requests"]
    rendered = JsonFormatter("search").format(record)
    assert "SECRET" not in rendered
    entry = json.loads(rendered)
    assert entry["request_id"] == identity
    assert entry["route"] == "/health"
    assert entry["status"] == 200
