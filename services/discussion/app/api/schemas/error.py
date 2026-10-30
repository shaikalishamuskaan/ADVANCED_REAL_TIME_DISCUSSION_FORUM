from typing import Any

from pydantic import BaseModel


class ErrorDetailSchema(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponseSchema(BaseModel):
    error: ErrorDetailSchema