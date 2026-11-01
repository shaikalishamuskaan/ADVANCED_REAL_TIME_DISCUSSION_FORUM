"""Locate the shared library for both service-local and Docker entry points."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forum_logging import RequestLoggingMiddleware, configure_logging, correlation_headers


def install_logging(app):
    configure_logging("notification_realtime")
    app.add_middleware(RequestLoggingMiddleware)
