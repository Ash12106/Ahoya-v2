"""Krawl decoy routes, origin verification, and ban enforcement."""

import asyncio
import hmac
from secrets import randbelow

from fastapi import Request
from pymongo.errors import PyMongoError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.client_identity import resolve_client_ip
from app.config import Settings
from app.errors import error_body
from app.krawl.service import DECOY_PATHS, decoy_response

HEALTH_PATHS = frozenset({"/health", "/health/db"})


class KrawlMiddleware(BaseHTTPMiddleware):
    """Guard app routes and handle exact honeypot paths."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        peer = request.client.host if request.client else None
        forwarded = request.headers.get("cf-connecting-ip")
        address = resolve_client_ip(
            peer,
            forwarded,
            self.settings.trusted_proxy_networks,
            production=self.settings.app_env == "production",
        )
        request_id = getattr(request.state, "request_id", "-")

        if path in DECOY_PATHS:
            await request.app.state.krawl.record_probe(path, address, request_id)
            delay_ms = self.settings.krawl_tarpit_min_ms + randbelow(
                self.settings.krawl_tarpit_max_ms - self.settings.krawl_tarpit_min_ms + 1
            )
            await asyncio.sleep(delay_ms / 1000)
            return decoy_response(path)

        if path not in HEALTH_PATHS and not self._has_valid_origin_token(request):
            return JSONResponse(
                status_code=403,
                content=error_body("ORIGIN_UNVERIFIED", "Request forbidden", request_id),
            )

        if path not in HEALTH_PATHS and address is not None:
            try:
                if await request.app.state.krawl.is_banned(address):
                    return JSONResponse(
                        status_code=429,
                        content=error_body(
                            "SOURCE_TEMPORARILY_BLOCKED", "Request refused", request_id
                        ),
                    )
            except PyMongoError:
                return JSONResponse(
                    status_code=503,
                    content=error_body(
                        "SECURITY_CHECK_UNAVAILABLE", "Service unavailable", request_id
                    ),
                )

        return await call_next(request)

    def _has_valid_origin_token(self, request: Request) -> bool:
        if self.settings.app_env != "production":
            return True
        expected = self.settings.cloudflare_origin_token
        received = request.headers.get("x-ahoya-origin-token", "")
        if expected is None:
            return False
        return hmac.compare_digest(
            expected.get_secret_value().encode("utf-8"),
            received.encode("utf-8"),
        )
