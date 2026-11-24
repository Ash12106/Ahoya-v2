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
        409: ("CONFLICT", "The requested profile change conflicts with saved data"),
        429: ("RATE_LIMITED", "Too many requests"),
        503: ("SERVICE_UNAVAILABLE", "Service temporarily unavailable"),
    }.get(exc.status_code, ("REQUEST_FAILED", "Request failed"))
    if exc.status_code == 409:
        code, message = {
            "username_unavailable": ("USERNAME_UNAVAILABLE", "That username is unavailable"),
            "date_of_birth_locked": (
                "DATE_OF_BIRTH_LOCKED",
                "Date of birth cannot be changed after profile creation",
            ),
            "profile_conflict": (
                "PROFILE_CONFLICT",
                "The profile update conflicts with saved data",
            ),
        }.get(str(exc.detail), (code, message))
    if exc.status_code == 429 and exc.detail == "username_change_limit":
        code, message = (
            "USERNAME_CHANGE_LIMIT",
            "Usernames can be changed at most twice in a rolling seven-day period",
        )
    if exc.status_code == 429 and exc.detail == "contact_email_change_limit":
        code, message = (
            "CONTACT_EMAIL_CHANGE_LIMIT",
            "Contact email can be changed at most twice in a rolling seven-day period",
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message),
        headers=exc.headers,
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", "An unexpected error occurred"),
    )
