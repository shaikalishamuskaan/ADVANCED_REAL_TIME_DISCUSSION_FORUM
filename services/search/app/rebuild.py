"""Run with: python -m app.rebuild --discussion-url http://your-discussion-service"""

import argparse
import asyncio
import sys

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.clients.discussion_export import DiscussionExportClient
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, engine
from app.services.rebuild import rebuild_index


async def run_rebuild(discussion_url: str):
    try:
        async with httpx.AsyncClient(base_url=discussion_url, timeout=10.0) as client:
            export = DiscussionExportClient(client, get_settings().SEARCH_SERVICE_KEY)
            async with AsyncSessionLocal() as session:
                return await rebuild_index(session, export)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Atomically replace the Search index from Discussion's internal export. Requires SEARCH_SERVICE_KEY matching Discussion. Live index writes wait while rebuilding.")
    parser.add_argument("--discussion-url", required=True, help="Discussion service base URL")
    args = parser.parse_args()
    url = httpx.URL(args.discussion_url)
    if url.scheme not in {"http", "https"} or not url.host or url.username or url.password:
        parser.error("Use an HTTP(S) Discussion URL without embedded credentials")
    try:
        counts = asyncio.run(run_rebuild(str(url)))
    except (httpx.HTTPError, SQLAlchemyError, ValueError) as exc:
        print(f"Search rebuild failed ({type(exc).__name__}); check service connectivity, export data, and SEARCH_SERVICE_KEY. No partial rebuild is committed.", file=sys.stderr)
        return 1
    print(f"Search rebuilt: {counts['thread']} threads and {counts['comment']} comments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
