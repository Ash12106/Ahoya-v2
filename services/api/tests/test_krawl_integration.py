import base64
import json
from datetime import UTC, datetime
from ipaddress import ip_address
from os import environ
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_database_login_profile_encryption_replay_and_logout() -> None:
    uri = environ.get("TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TEST_MONGODB_URI is not configured")

    observer = AsyncMongoClient(uri, serverSelectionTimeoutMS=2000)
    database_name = f"ahoya_profile_test_{uuid4().hex}"
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pii_key = b"p" * 32
    settings = Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri=uri,
        database_name=database_name,
        krawl_hmac_secret="p" * 40,
        web_assertion_public_keys=json.dumps(
            {"integration-key": base64.b64encode(public_der).decode()}
        ),
        pii_encryption_keys=json.dumps({"integration-pii": base64.b64encode(pii_key).decode()}),
        pii_encryption_active_key_id="integration-pii",
        dob_collection_enabled=True,
        dob_collection_notice_version="test-notice-v1",
        dob_collection_notice_text="Synthetic integration-test consent notice.",
    )
    issued_at = int(datetime.now(UTC).timestamp())
    assertion = jwt.encode(
        {
            "iss": "ahoya-web",
            "aud": "ahoya-api",
            "sub": "google-subject-for-integration-test",
            "provider": "google",
            "jti": uuid4().hex + uuid4().hex,
            "iat": issued_at,
            "exp": issued_at + 60,
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "integration-key", "typ": "JWT"},
    )
    app = create_app(settings=settings)

    try:
        await observer.admin.command({"ping": 1})
        with TestClient(app) as web:
            readiness = web.get("/health/phase1")
            assert readiness.status_code == 200
            assert await observer[database_name]["security_events"].count_documents({}) == 0

            login = web.post(
                "/v1/auth/sessions",
                headers={"Authorization": f"Bearer {assertion}"},
            )
            assert login.status_code == 200
            session_token = login.json()["session_token"]
            account = await observer[database_name]["users"].find_one(
                {"google_subject": "google-subject-for-integration-test"},
                projection={"_id": 1},
            )
            assert account is not None
            user_id = account["_id"]
            auth_headers = {"Authorization": f"Bearer {session_token}"}

            empty_profile = web.get("/v1/profiles/me", headers=auth_headers)
            assert empty_profile.status_code == 200
            assert empty_profile.json()["profile"] is None
            assert empty_profile.json()["date_of_birth_collection_enabled"] is True

            basic_profile = web.patch(
                "/v1/profiles/me",
                headers=auth_headers,
                json={
                    "username": "test_person",
                    "display_name": "Test Person",
                    "cover_alt_text": "",
                },
            )
            assert basic_profile.status_code == 200
            assert basic_profile.json()["profile"]["date_of_birth"] is None
            without_dob = await observer[database_name]["profiles"].find_one(
                {"user_id": user_id},
                projection={"_id": 0},
            )
            assert without_dob is not None
            assert not any(key.startswith("dob_") for key in without_dob)

            consent = web.post(
                "/v1/consents",
                headers=auth_headers,
                json={
                    "purpose": "self_declared_date_of_birth",
                    "notice_version": "test-notice-v1",
                    "consented": True,
                },
            )
            assert consent.status_code == 201
            saved = web.patch(
                "/v1/profiles/me",
                headers=auth_headers,
                json={
                    "username": "test_person",
                    "display_name": "Test Person",
                    "date_of_birth": "2000-01-02",
                    "cover_alt_text": "",
                },
            )
            assert saved.status_code == 200
            assert saved.json()["profile"]["date_of_birth"] == "2000-01-02"
            document = await observer[database_name]["profiles"].find_one(
                {"user_id": user_id},
                projection={"_id": 0},
            )
            assert document is not None
            assert "date_of_birth" not in document
            assert "2000-01-02" not in json.dumps(document, default=str)
            assert (
                await observer[database_name]["consent_events"].count_documents(
                    {"user_id": user_id, "notice_version": "test-notice-v1"}
                )
                == 1
            )

            replay = web.post(
                "/v1/auth/sessions",
                headers={"Authorization": f"Bearer {assertion}"},
            )
            assert replay.status_code == 401
            logout = web.delete("/v1/auth/sessions/current", headers=auth_headers)
            assert logout.status_code == 204
            assert web.get("/v1/profiles/me", headers=auth_headers).status_code == 401
    finally:
        await observer.drop_database(database_name)
        await observer.close()
