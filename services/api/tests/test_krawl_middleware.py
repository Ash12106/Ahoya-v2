from ipaddress import ip_address

import pytest
from fastapi import FastAPI
from pymongo.errors import ServerSelectionTimeoutError
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.config import Settings
from app.krawl.middleware import KrawlMiddleware


class StubKrawl:
    def __init__(self, banned: bool = False, fail: bool = False) -> None:
        self.banned = banned
        self.fail = fail
        self.probes: list[tuple[str, object, str]] = []

    async def record_probe(self, path: str, address: object, request_id: str) -> None:
        self.probes.append((path, address, request_id))

    async def is_banned(self, address: object) -> bool:
        if self.fail:
            raise ServerSelectionTimeoutError("private connection detail")
        return self.banned


def make_settings(production: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        app_env="production" if production else "test",
        mongodb_uri="mongodb://localhost:27017",
        database_name="ahoya_test",
        krawl_hmac_secret="m" * 40,
        cloudflare_origin_token="o" * 40 if production else None,
        trusted_proxy_cidrs="192.0.2.0/24" if production else "",
        cors_allowed_origins="https://ahoya.example" if production else "http://localhost:3000",
        krawl_tarpit_min_ms=100,
        krawl_tarpit_max_ms=100,
    )


def make_request(
    path: str,
    peer: str = "192.0.2.8",
    headers: dict[str, str] | None = None,
) -> tuple[Request, StubKrawl]:
    app = FastAPI()
    krawl = StubKrawl()
    app.state.krawl = krawl
    request_headers = [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": request_headers,
        "client": (peer, 12345),
        "server": ("test", 80),
        "state": {"request_id": "test-request-id"},
        "app": app,
    }
    return Request(scope), krawl


@pytest.mark.asyncio
async def test_decoy_probe_uses_only_a_trusted_cloudflare_address() -> None:
    request, krawl = make_request("/.env", headers={"cf-connecting-ip": "203.0.113.9"})
    middleware = KrawlMiddleware(lambda scope, receive, send: None, make_settings(production=True))

    response = await middleware.dispatch(request, lambda req: None)

    assert response.status_code == 404
    assert krawl.probes == [("/.env", ip_address("203.0.113.9"), "test-request-id")]


@pytest.mark.asyncio
async def test_protected_route_rejects_missing_origin_token() -> None:
    request, _ = make_request("/private")
    middleware = KrawlMiddleware(lambda scope, receive, send: None, make_settings(production=True))

    response = await middleware.dispatch(request, lambda req: None)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_protected_route_allows_token_and_unbanned_trusted_client() -> None:
    request, krawl = make_request(
        "/private",
        headers={
            "cf-connecting-ip": "203.0.113.9",
            "x-ahoya-origin-token": "o" * 40,
        },
    )
    middleware = KrawlMiddleware(lambda scope, receive, send: None, make_settings(production=True))

    async def call_next(req: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    assert await krawl.is_banned(ip_address("203.0.113.9")) is False


@pytest.mark.asyncio
async def test_banned_and_unavailable_security_checks_fail_closed() -> None:
    for fail, expected_status in ((False, 429), (True, 503)):
        request, krawl = make_request(
            "/private",
            headers={
                "cf-connecting-ip": "203.0.113.9",
                "x-ahoya-origin-token": "o" * 40,
            },
        )
        krawl.banned = not fail
        krawl.fail = fail
        middleware = KrawlMiddleware(
            lambda scope, receive, send: None, make_settings(production=True)
        )

        response = await middleware.dispatch(request, lambda req: None)

        assert response.status_code == expected_status
