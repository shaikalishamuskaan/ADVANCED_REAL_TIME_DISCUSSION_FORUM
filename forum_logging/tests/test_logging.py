import asyncio
import io
import json
import logging
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from forum_logging import (JsonFormatter, RequestLoggingMiddleware, correlation_headers,
                           logging_config, normalize_request_id, request_id)


class Capture:
    def __enter__(self):
        self.output = io.StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.handler.setFormatter(JsonFormatter("test-service"))
        self.logger = logging.getLogger("forum.requests")
        self.old = self.logger.handlers, self.logger.level, self.logger.propagate
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        return self

    def __exit__(self, *args):
        self.logger.handlers, level, self.logger.propagate = self.old
        self.logger.setLevel(level)

    def records(self):
        return [json.loads(line) for line in self.output.getvalue().splitlines()]


class FormatterTests(unittest.TestCase):
    def test_exception_and_unapproved_extra_values_are_not_logged(self):
        try:
            raise ValueError("password=SECRET recovery_code=SECRET token=SECRET")
        except ValueError:
            record = logging.LogRecord("app.worker", logging.ERROR, __file__, 1, "stream.failed", (), sys.exc_info())
        record.password = "SECRET"
        data = json.loads(JsonFormatter("notify").format(record))
        self.assertEqual(data["error_type"], "ValueError")
        self.assertTrue(data["stack"])
        self.assertNotIn("SECRET", json.dumps(data))
        self.assertEqual(data["service"], "notify")

    def test_websocket_transport_urls_are_not_logged(self):
        record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, 'WebSocket /ws?token=SECRET [accepted]', (), None)
        self.assertNotIn("SECRET", JsonFormatter("realtime").format(record))

    def test_invalid_request_ids_are_replaced(self):
        for value in [None, "", "bad\r\nLOG-FORGERY", "x" * 1000]:
            result = normalize_request_id(value)
            self.assertEqual(len(result), 32)
            int(result, 16)

    def test_uuid_request_ids_are_normalized(self):
        self.assertEqual(normalize_request_id("11111111-2222-4333-8444-555555555555"), "11111111222243338444555555555555")

    def test_log_levels_are_configurable_with_safe_default(self):
        with patch.dict("os.environ", {"LOG_LEVEL": "debug"}):
            self.assertEqual(logging_config("search")["root"]["level"], "DEBUG")
            self.assertEqual(logging_config("search")["loggers"]["uvicorn.error"]["level"], "INFO")
            self.assertEqual(logging_config("search")["loggers"]["websockets"]["level"], "WARNING")
            self.assertEqual(logging_config("search")["loggers"]["django.db.backends"]["level"], "WARNING")
        with patch.dict("os.environ", {"LOG_LEVEL": "invalid"}):
            self.assertEqual(logging_config("search")["root"]["level"], "INFO")


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def run_http(self, app, identity=b"11111111222243338444555555555555"):
        scope = {"type": "http", "method": "POST", "path": "/api/auth/login",
                 "query_string": b"password=SECRET", "headers": [(b"x-request-id", identity),
                 (b"authorization", b"Bearer SECRET"), (b"cookie", b"refresh_token=SECRET")]}
        sent = []
        async def send(message): sent.append(message)
        async def receive(): raise AssertionError("Middleware must not consume the request body")
        await RequestLoggingMiddleware(app)(scope, receive, send)
        return sent

    async def test_response_and_streaming_body_are_preserved_without_logging_secrets(self):
        async def app(scope, receive, send):
            scope["route"] = SimpleNamespace(path="/api/auth/login")
            await send({"type": "http.response.start", "status": 400, "headers": [(b"retry-after", b"10")]})
            await send({"type": "http.response.body", "body": b"SECRET", "more_body": True})
            await send({"type": "http.response.body", "body": b"end"})
        with Capture() as logs:
            sent = await self.run_http(app)
        self.assertEqual(sent[1]["body"], b"SECRET")
        self.assertTrue(sent[1]["more_body"])
        self.assertIn((b"retry-after", b"10"), sent[0]["headers"])
        self.assertIn((b"x-request-id", b"11111111222243338444555555555555"), sent[0]["headers"])
        entry, = logs.records()
        self.assertEqual(entry["status"], 400)
        self.assertEqual(entry["route"], "/api/auth/login")
        self.assertGreaterEqual(entry["duration_ms"], 0)
        self.assertNotIn("SECRET", logs.output.getvalue())
        self.assertIsNone(request_id.get())

    async def test_unmatched_paths_are_not_recorded_raw(self):
        async def app(scope, receive, send):
            scope["path"] = "/SECRET"
            await send({"type": "http.response.start", "status": 404})
        with Capture() as logs:
            await self.run_http(app)
        self.assertEqual(logs.records()[0]["route"], "<unmatched>")
        self.assertNotIn("SECRET", logs.output.getvalue())

    async def test_failure_is_reraised_and_request_context_is_cleared(self):
        async def app(scope, receive, send): raise RuntimeError("SECRET")
        with Capture() as logs:
            with self.assertRaises(RuntimeError): await self.run_http(app)
        entry, = logs.records()
        self.assertEqual(entry["status"], 500)
        self.assertEqual(entry["error_type"], "RuntimeError")
        self.assertNotIn("SECRET", logs.output.getvalue())
        self.assertIsNone(request_id.get())

    async def test_concurrent_requests_keep_separate_correlation_headers(self):
        observed = []
        async def app(scope, receive, send):
            await asyncio.sleep(0)
            observed.append(correlation_headers()["X-Request-ID"])
            await send({"type": "http.response.start", "status": 200})
        with Capture() as logs:
            await asyncio.gather(self.run_http(app, b"1"*32), self.run_http(app, b"2"*32))
        self.assertEqual(set(observed), {"1"*32,"2"*32})
        self.assertEqual({item["request_id"] for item in logs.records()}, set(observed))
        self.assertEqual(correlation_headers(), {})

    async def test_websocket_messages_are_forwarded_without_logging_payloads(self):
        sent = []
        incoming = iter([{"type":"websocket.receive","text":"SECRET"}, {"type":"websocket.disconnect","code":1001}])
        async def receive(): return next(incoming)
        async def send(message): sent.append(message)
        async def app(scope, receive, send):
            self.assertEqual((await receive())["text"], "SECRET")
            await send({"type":"websocket.accept"})
            await receive()
        with Capture() as logs:
            await RequestLoggingMiddleware(app)({"type":"websocket","path":"/ws","headers":[]},receive,send)
        entry, = logs.records()
        self.assertTrue(entry["accepted"])
        self.assertEqual(entry["close_code"],1001)
        self.assertNotIn("SECRET",logs.output.getvalue())

    async def test_lifespan_is_untouched(self):
        called=[]
        async def app(scope,receive,send): called.append(scope["type"])
        with Capture() as logs:
            await RequestLoggingMiddleware(app)({"type":"lifespan"},None,None)
        self.assertEqual(called,["lifespan"])
        self.assertEqual(logs.records(),[])
