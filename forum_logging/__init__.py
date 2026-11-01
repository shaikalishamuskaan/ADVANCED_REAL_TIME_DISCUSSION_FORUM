"""Shared, standard-library logging for the independently run forum services."""
import json
import logging
import logging.config
import os
import sys
import time
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

request_id = ContextVar("forum_request_id", default=None)
FIELDS = ("method", "route", "status", "duration_ms", "close_code", "accepted",
          "event_id", "message_id", "stream", "consumer", "attempts")


def normalize_request_id(value):
    try:
        return UUID(value).hex if isinstance(value, str) and len(value) <= 36 else uuid4().hex
    except ValueError:
        return uuid4().hex


def correlation_headers():
    value = request_id.get()
    return {"X-Request-ID": value} if value else {}


class JsonFormatter(logging.Formatter):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def format(self, record):
        event = record.getMessage()
        # Framework WebSocket transport messages can contain the raw URL.
        if record.name.startswith("uvicorn") and "WebSocket" in event:
            event = "websocket.transport"
        if record.name.startswith("django.security"):
            event = record.name
        data = {"timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname, "service": self.service,
                "logger": record.name, "event": event,
                "request_id": getattr(record, "request_id", request_id.get())}
        for field in FIELDS:
            if hasattr(record, field):
                data[field] = getattr(record, field)
        if record.exc_info and record.exc_info[0]:
            data["error_type"] = record.exc_info[0].__name__
            # Exception messages, source lines and locals may contain credentials
            # or SQL parameters. Keep only safe stack locations for diagnostics.
            data["stack"] = [{"file": Path(frame.filename).name, "line": frame.lineno,
                              "function": frame.name}
                             for frame in traceback.extract_tb(record.exc_info[2])]
        return json.dumps(data, ensure_ascii=True, default=str)


def logging_config(service):
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        level = "INFO"
    return {
        "version": 1, "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonFormatter, "service": service}},
        "handlers": {"console": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "json"}},
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            "uvicorn": {"handlers": [], "propagate": True, "level": "INFO"},
            "uvicorn.error": {"handlers": [], "propagate": True, "level": "INFO"},
            "uvicorn.access": {"handlers": [], "propagate": False, "level": "CRITICAL"},
            "django": {"handlers": [], "propagate": True, "level": level},
            "django.request": {"handlers": [], "propagate": False, "level": "CRITICAL"},
            "django.server": {"handlers": [], "propagate": False, "level": "CRITICAL"},
            "httpx": {"handlers": [], "propagate": True, "level": "WARNING"},
            "httpcore": {"handlers": [], "propagate": True, "level": "WARNING"},
            "sqlalchemy.engine": {"handlers": [], "propagate": True, "level": "WARNING"},
            "django.db.backends": {"handlers": [], "propagate": True, "level": "WARNING"},
            "websockets": {"handlers": [], "propagate": True, "level": "WARNING"},
        },
    }


def configure_logging(service):
    logging.config.dictConfig(logging_config(service))


class RequestLoggingMiddleware:
    """Pure ASGI: observes metadata without consuming HTTP or WebSocket bodies."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        incoming = next((value.decode("latin-1") for key, value in scope.get("headers", [])
                         if key.lower() == b"x-request-id"), None)
        identity = normalize_request_id(incoming)
        token = request_id.set(identity)
        scope.setdefault("state", {})["request_id"] = identity
        started = time.monotonic()
        status, accepted, close_code, failure = 500, False, None, None

        async def observe_send(message):
            nonlocal status, accepted, close_code
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message["headers"] = headers + [(b"x-request-id", identity.encode("ascii"))]
            elif message["type"] == "websocket.accept":
                accepted = True
            elif message["type"] == "websocket.close":
                close_code = message.get("code", 1000)
            await send(message)

        async def observe_receive():
            nonlocal close_code
            message = await receive()
            if message["type"] == "websocket.disconnect":
                close_code = message.get("code", 1000)
            return message

        try:
            await self.app(scope, observe_receive, observe_send)
        except Exception:
            failure = sys.exc_info()
            raise
        finally:
            try:
                route = getattr(scope.get("route"), "path", "<unmatched>")
                fields = {"request_id": identity, "route": route, "duration_ms": round((time.monotonic() - started) * 1000, 2)}
                if kind == "http":
                    fields.update(method=scope.get("method"), status=500 if failure else status)
                else:
                    fields.update(accepted=accepted, close_code=close_code)
                logging.getLogger("forum.requests").log(
                    logging.ERROR if failure or (kind == "http" and status >= 500) else logging.INFO,
                    "http.request" if kind == "http" else "websocket.closed",
                    extra=fields, exc_info=failure,
                )
            finally:
                request_id.reset(token)
