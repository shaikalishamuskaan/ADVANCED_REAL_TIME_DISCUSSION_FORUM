import logging
import time

from forum_logging import normalize_request_id, request_id


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_exception(self, request, exception):
        logging.getLogger("forum.requests").error(
            "http.exception", exc_info=(type(exception), exception, exception.__traceback__),
        )

    def __call__(self, request):
        identity = normalize_request_id(request.headers.get("X-Request-ID"))
        request.request_id = identity
        token = request_id.set(identity)
        started = time.monotonic()
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
            response["X-Request-ID"] = identity
            return response
        finally:
            try:
                match = getattr(request, "resolver_match", None)
                logging.getLogger("forum.requests").log(
                    logging.ERROR if status >= 500 else logging.INFO, "http.request",
                    extra={"request_id": identity, "method": request.method, "route": getattr(match, "route", "<unmatched>"),
                           "status": status, "duration_ms": round((time.monotonic() - started) * 1000, 2)},
                )
            finally:
                request_id.reset(token)
