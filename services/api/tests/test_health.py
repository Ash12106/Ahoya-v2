from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient
from pymongo.errors import ServerSelectionTimeoutError

from app.config import Settings
from app.main import create_app


class FakeAdmin:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def command(self, command: dict[str, int]) -> dict[str, int]:
        if self.fail:
            raise ServerSelectionTimeoutError("hidden test detail")
        return {"ok": 1}


class FakeDatabase:
    def __getitem__(self, name: str) -> object:
        return object()


class FakeMongoClient:
    def __init__(self, fail: bool = False) -> None:
        self.admin = FakeAdmin(fail)
        self.closed = False

    def __getitem__(self, name: str) -> FakeDatabase:
        return FakeDatabase()

    async def close(self) -> None:
        self.closed = True


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri="mongodb://localhost:27017",
        database_name="ahoya_test",
        krawl_hmac_secret="t" * 40,
    )


@contextmanager
def client_for(fail: bool = False) -> Iterator[TestClient]:
    fake = FakeMongoClient(fail)
    app = create_app(
        settings=make_settings(),
        mongo_client_factory=lambda uri: cast(AsyncMongoClient, fake),
        initialize_indexes=False,
    )
    with TestClient(app) as client:
        yield client


def test_liveness_returns_a_generated_request_id() -> None:
    with client_for() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.json()["request_id"]


def test_database_health_passes_for_a_successful_ping() -> None:
    with client_for() as client:
        response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_database_health_hides_driver_errors() -> None:
    with client_for(fail=True) as client:
        response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "hidden test detail" not in response.text
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_unmatched_route_uses_the_error_envelope() -> None:
    with client_for() as client:
        response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_cors_allows_only_the_configured_web_origin() -> None:
    with client_for() as client:
        allowed = client.get("/health", headers={"Origin": "http://localhost:3000"})
        denied = client.get("/health", headers={"Origin": "https://attacker.example"})

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in denied.headers


def test_production_rejects_requests_without_the_origin_token() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        mongodb_uri="mongodb://localhost:27017",
        database_name="ahoya_test",
        krawl_hmac_secret="t" * 40,
        cloudflare_origin_token="o" * 40,
        trusted_proxy_cidrs="127.0.0.1/32",
        cors_allowed_origins="https://ahoya.example",
    )
    fake = FakeMongoClient()
    app = create_app(
        settings=settings,
        mongo_client_factory=lambda uri: cast(AsyncMongoClient, fake),
        initialize_indexes=False,
    )

    with TestClient(app) as client:
        response = client.get("/protected")

    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_UNVERIFIED"
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_krawl_secret_must_be_at_least_32_characters() -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            app_env="test",
            mongodb_uri="mongodb://localhost:27017",
            database_name="ahoya_test",
            krawl_hmac_secret="short",
        )
