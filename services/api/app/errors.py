"""Consistent API error responses."""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import request_id_context


def error_body(code: str, message: str, request_id: str | None = None) -> dict[str, str]:
    """Create the public error envelope without internal details."""
    return {
        "code": code,
        "message": message,
        "request_id": request_id or request_id_context.get(),
    }


async def validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    del request, exc
    return JSONResponse(
        status_code=422,
        content=error_body("VALIDATION_ERROR", "Invalid request"),
    )


async def http_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    del request
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code, message = {
        401: ("UNAUTHENTICATED", "Authentication required"),
        403: ("FORBIDDEN", "Request forbidden"),
        404: ("NOT_FOUND", "Resource not found"),
    }.get(exc.status_code, ("REQUEST_FAILED", "Request failed"))
    return JSONResponse(status_code=exc.status_code, content=error_body(code, message))


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", "An unexpected error occurred"),
    )
