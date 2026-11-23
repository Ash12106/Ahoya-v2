from ipaddress import ip_address
from os import environ
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

from app.config import Settings
from app.database import ensure_foundation_indexes
from app.krawl.service import KrawlService
from app.main import create_app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repeat_probe_is_recorded_and_banned() -> None:
    uri = environ.get("TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TEST_MONGODB_URI is not configured")

    client = AsyncMongoClient(uri, serverSelectionTimeoutMS=2000)
    database_name = f"ahoya_test_{uuid4().hex}"
    database = client[database_name]
    settings = Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri=uri,
        database_name=database_name,
        krawl_hmac_secret="i" * 40,
        krawl_ban_threshold=2,
    )
    await client.admin.command({"ping": 1})
    await ensure_foundation_indexes(database, settings.security_event_retention_days)
    service = KrawlService(database, settings)
    source_ip = ip_address("192.0.2.18")

    try:
        first = await service.record_probe("/.env", source_ip, "request-one")
        second = await service.record_probe("/wp-admin", source_ip, "request-two")

        assert first.hit_count == 1
        assert first.banned_until is None
        assert second.hit_count == 2
        assert second.banned_until is not None
        assert await service.is_banned(source_ip)
        assert await database["security_events"].count_documents({"event_type": "decoy_probe"}) == 2
    finally:
        await client.drop_database(database_name)
        await client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_readiness_and_decoy_route_use_real_mongodb() -> None:
    uri = environ.get("TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TEST_MONGODB_URI is not configured")

    observer = AsyncMongoClient(uri, serverSelectionTimeoutMS=2000)
    database_name = f"ahoya_api_test_{uuid4().hex}"
    settings = Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri=uri,
        database_name=database_name,
        krawl_hmac_secret="a" * 40,
        krawl_tarpit_min_ms=100,
        krawl_tarpit_max_ms=100,
    )
    app = create_app(settings=settings)

    try:
        with TestClient(app) as web:
            readiness = web.get("/health/db")
            probe = web.get("/.env")

        assert readiness.status_code == 200
        assert probe.status_code == 404
        assert probe.headers["cache-control"] == "no-store"
        stored_event = await observer[database_name]["security_events"].find_one(
            {"request_id": probe.headers["x-request-id"]},
            projection={"event_type": 1, "client_ip_hash": 1},
        )
        assert stored_event is not None
        assert stored_event["event_type"] == "decoy_probe"
        assert stored_event["client_ip_hash"] is None
    finally:
        await observer.drop_database(database_name)
        await observer.close()
