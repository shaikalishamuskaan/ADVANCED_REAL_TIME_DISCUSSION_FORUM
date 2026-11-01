"""Construct container-only database URLs without putting credentials in argv."""
import os
import sys
from urllib.parse import quote


if database := os.environ.get("FORUM_DATABASE"):
    user = quote(os.environ["POSTGRES_USER"], safe="")
    password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
    host = os.environ.get("POSTGRES_HOST", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"

if len(sys.argv) < 2:
    raise SystemExit("A service command is required")
os.execvp(sys.argv[1], sys.argv[1:])
