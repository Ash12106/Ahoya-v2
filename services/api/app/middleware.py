"""Request context and response security headers."""

import logging
import time
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import error_body
from app.logging_config import request_id_context, set_request_id

logger = logging.getLogger("ahoya.request")


class RequestIdMiddleware:
    """Generate a request ID, return it to the caller, and log the outcome."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = set_request_id(request_id)
        started_at = time.perf_counter()
        status_code = 500
        method = str(scope.get("method", "UNKNOWN"))
        path = str(scope.get("path", "/"))
        route_group = "health" if path.startswith("/health") else "api"

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            logger.error(
                "unhandled_request_error",
                extra={"error_type": type(exc).__name__},
            )
            response = JSONResponse(
                status_code=500,
                content=error_body("INTERNAL_ERROR", "An unexpected error occurred", request_id),
                headers={"X-Request-ID": request_id},
            )
            await response(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "request_complete",
                extra={
                    "method": method,
                    "route_group": route_group,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_context.reset(token)


class SecurityHeadersMiddleware:
    """Set baseline security headers on every API response."""

    def __init__(self, app: ASGIApp, app_env: str) -> None:
        self.app = app
        self.app_env = app_env

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                headers["Content-Security-Policy"] = (
                    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                )
                if self.app_env == "production":
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        await self.app(scope, receive, send_with_headers)
