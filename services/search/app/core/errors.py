import logging
import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException


def error_response(status_code: int, code: str, message: str, details=None, headers=None):
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
        headers=headers,
    )


def install_error_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
        codes = {
            400: "validation_error", 401: "unauthenticated", 403: "forbidden",
            404: "not_found", 422: "unprocessable", 429: "rate_limited",
            503: "dependency_unavailable",
        }
        return error_response(
            exc.status_code, codes.get(exc.status_code, "http_error"),
            str(exc.detail), headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"][1:])
        return error_response(400, "validation_error", first["msg"], {"field": field})

    async def dependency_error(request: Request, exc: Exception):
        logging.getLogger(__name__).error(
            "dependency.unavailable", exc_info=(type(exc), exc, exc.__traceback__),
        )
        # Keep database URLs, service keys, and upstream response bodies private.
        return error_response(503, "dependency_unavailable", "A required service is unavailable")

    app.add_exception_handler(SQLAlchemyError, dependency_error)
    app.add_exception_handler(httpx.HTTPError, dependency_error)
