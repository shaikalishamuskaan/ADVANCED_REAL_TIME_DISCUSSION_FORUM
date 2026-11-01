import json
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from config.request_logging import RequestLoggingMiddleware
from forum_logging import JsonFormatter, correlation_headers, request_id


class RequestLoggingTests(SimpleTestCase):
    def test_request_is_correlated_without_logging_credentials(self):
        identity = "11111111222243338444555555555555"
        request = RequestFactory().post("/api/auth/login?password=SECRET", {"password":"SECRET"},
            HTTP_X_REQUEST_ID=identity, HTTP_AUTHORIZATION="Bearer SECRET", HTTP_COOKIE="refresh_token=SECRET")
        request.resolver_match = SimpleNamespace(route="api/auth/login")
        def respond(request):
            self.assertEqual(correlation_headers(), {"X-Request-ID":identity})
            return HttpResponse("SECRET",status=403)
        with self.assertLogs("forum.requests",level="INFO") as logs:
            response = RequestLoggingMiddleware(respond)(request)
        self.assertEqual(response.status_code,403)
        self.assertEqual(response["X-Request-ID"],identity)
        rendered = JsonFormatter("identity").format(logs.records[0])
        self.assertNotIn("SECRET",rendered)
        self.assertEqual(json.loads(rendered)["status"],403)
        self.assertIsNone(request_id.get())

    def test_context_is_cleared_when_handler_fails(self):
        request = RequestFactory().get("/")
        def respond(request): raise RuntimeError("SECRET")
        with self.assertLogs("forum.requests",level="ERROR"):
            with self.assertRaises(RuntimeError): RequestLoggingMiddleware(respond)(request)
        self.assertIsNone(request_id.get())
