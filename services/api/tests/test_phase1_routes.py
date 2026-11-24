import base64
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from app.config import Settings
from app.main import create_app


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    async def insert_one(
        self,
        document: dict[str, Any],
        session: object | None = None,
    ) -> None:
        del session
        document_id = str(document["_id"]) if "_id" in document else uuid4().hex
        if document_id in self.documents:
            raise DuplicateKeyError("duplicate key")
        self.documents[document_id] = dict(document)

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool,
        return_document: object,
        session: object | None = None,
    ) -> dict[str, Any] | None:
        del return_document, session
        if "google_subject" in query:
            subject = query["google_subject"]
            document = next(
                (item for item in self.documents.values() if item.get("google_subject") == subject),
                None,
            )
        else:
            document = self.documents.get(str(query["_id"]))
        if document is None:
            if not upsert:
                return None
            document = {"_id": query.get("_id", update.get("$setOnInsert", {}).get("_id"))}
            self.documents[str(document["_id"])] = document
            document.update(update.get("$setOnInsert", {}))
        for field, amount in update.get("$inc", {}).items():
            document[field] = document.get(field, 0) + amount
        document.update(update.get("$set", {}))
        return dict(document)

    async def find_one(
        self,
        query: dict[str, Any],
        projection: dict[str, int] | None = None,
        session: object | None = None,
    ) -> dict[str, Any] | None:
        del projection, session
        for key, document in self.documents.items():
            matched = True
            for name, value in query.items():
                actual = key if name == "_id" else document.get(name)
                if isinstance(value, dict):
                    if "$exists" in value and (name in document) != value["$exists"]:
                        matched = False
                    if "$gt" in value and (actual is None or actual <= value["$gt"]):
                        matched = False
                elif actual != value:
                    matched = False
            if matched:
                return dict(document)
        return None

    async def update_one(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
        session: object | None = None,
    ) -> None:
        del session
        key = str(query.get("_id", query.get("user_id", "")))
        document = self.documents.get(key)
        if document is None and upsert:
            document = dict(update.get("$setOnInsert", {}))
            self.documents[key] = document
        if document is not None:
            document.update(update.get("$set", {}))
            for field in update.get("$unset", {}):
                document.pop(field, None)


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection())


class FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    async def start_transaction(self) -> FakeTransaction:
        return FakeTransaction()


class FakeBoundSession:
    async def __aenter__(self) -> FakeSession:
        return FakeSession()

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSessionStart:
    def bind(self) -> FakeBoundSession:
        return FakeBoundSession()


class FakeAdmin:
    async def command(self, command: dict[str, int]) -> dict[str, int]:
        del command
        return {"ok": 1}


class FakeMongoClient:
    def __init__(self) -> None:
        self.admin = FakeAdmin()
        self.database = FakeDatabase()

    def __getitem__(self, name: str) -> FakeDatabase:
        del name
        return self.database

    def start_session(self) -> FakeSessionStart:
        return FakeSessionStart()

    async def close(self) -> None:
        return None


def make_settings(enabled: bool = True) -> tuple[Settings, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri="mongodb://localhost:27017",
        database_name="ahoya_test",
        krawl_hmac_secret="r" * 40,
        web_assertion_public_keys=json.dumps({"test-key": base64.b64encode(public_der).decode()}),
        pii_encryption_keys=json.dumps({"test-pii": base64.b64encode(b"k" * 32).decode()}),
        pii_encryption_active_key_id="test-pii",
        dob_collection_enabled=enabled,
        dob_collection_notice_version="test-v1" if enabled else "",
        dob_collection_notice_text="Test-only notice." if enabled else "",
    )
    return settings, private_key


def make_assertion(private_key: Ed25519PrivateKey) -> str:
    issued_at = int(datetime.now(UTC).timestamp())
    return jwt.encode(
        {
            "iss": "ahoya-web",
            "aud": "ahoya-api",
            "sub": "google-subject-for-route-test",
            "provider": "google",
            "jti": uuid4().hex + uuid4().hex,
            "iat": issued_at,
            "exp": issued_at + 60,
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "test-key", "typ": "JWT"},
    )


def test_session_profile_consent_and_logout_use_server_side_state() -> None:
    settings, private_key = make_settings()
    mongo = FakeMongoClient()
    app = create_app(
        settings=settings,
        mongo_client_factory=lambda uri: cast(AsyncMongoClient, mongo),
        initialize_indexes=False,
    )
    assertion = make_assertion(private_key)

    with TestClient(app) as web:
        app.state.phase1_writes_ready = True
        login = web.post("/v1/auth/sessions", headers={"Authorization": f"Bearer {assertion}"})
        assert login.status_code == 200
        token = login.json()["session_token"]
        assert token not in json.dumps(mongo.database["auth_sessions"].documents, default=str)
        headers = {"Authorization": f"Bearer {token}"}

        empty = web.get("/v1/profiles/me", headers=headers)
        assert empty.status_code == 200
        assert empty.json()["profile"] is None
        assert (
            web.get("/v1/auth/me", headers=headers).json()["account"]["profile_complete"] is False
        )

        consent = web.post(
            "/v1/consents",
            headers=headers,
            json={
                "purpose": "self_declared_date_of_birth",
                "notice_version": "test-v1",
                "consented": True,
            },
        )
        assert consent.status_code == 201

        saved = web.patch(
            "/v1/profiles/me",
            headers=headers,
            json={
                "username": "profile_owner",
                "display_name": "Profile Owner",
                "date_of_birth": "1998-03-14",
                "cover_alt_text": "",
                "contact_email": "ash@example.com",
                "phone_number": "+91 (98765) 43210",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["profile"]["date_of_birth"] == "1998-03-14"
        assert saved.json()["profile"]["contact_email"] == "ash@example.com"
        assert saved.json()["profile"]["phone_number"] == "+919876543210"
        assert saved.json()["contact_email_changes_remaining"] == 2
        profile_document = next(iter(mongo.database["profiles"].documents.values()))
        assert "1998-03-14" not in json.dumps(profile_document, default=str)
        assert "ash@example.com" not in json.dumps(profile_document, default=str)
        assert "+919876543210" not in json.dumps(profile_document, default=str)
        assert len(mongo.database["consent_events"].documents) == 1

        read_back = web.get("/v1/profiles/me", headers=headers)
        assert read_back.json()["profile"]["date_of_birth"] == "1998-03-14"
        assert read_back.json()["profile"]["contact_email"] == "ash@example.com"
        assert read_back.json()["profile"]["phone_number"] == "+919876543210"

        for email, remaining in (("ash2@example.com", 1), ("ash3@example.com", 0)):
            changed = web.patch(
                "/v1/profiles/me",
                headers=headers,
                json={
                    "username": "profile_owner",
                    "display_name": "Profile Owner",
                    "cover_alt_text": "",
                    "contact_email": email,
                },
            )
            assert changed.status_code == 200
            assert changed.json()["contact_email_changes_remaining"] == remaining
            assert changed.json()["profile"]["phone_number"] == "+919876543210"

        limited = web.patch(
            "/v1/profiles/me",
            headers=headers,
            json={
                "username": "profile_owner",
                "display_name": "Profile Owner",
                "cover_alt_text": "",
                "contact_email": "ash4@example.com",
            },
        )
        assert limited.status_code == 429
        assert limited.json()["code"] == "CONTACT_EMAIL_CHANGE_LIMIT"

        cleared = web.patch(
            "/v1/profiles/me",
            headers=headers,
            json={
                "username": "profile_owner",
                "display_name": "Profile Owner",
                "cover_alt_text": "",
                "contact_email": None,
                "phone_number": None,
            },
        )
        assert cleared.status_code == 200
        assert cleared.json()["profile"]["contact_email"] is None
        assert cleared.json()["profile"]["phone_number"] is None
        profile_document = next(iter(mongo.database["profiles"].documents.values()))
        assert not any(
            key in profile_document
            for key in (
                "contact_email_key_id",
                "contact_email_nonce",
                "contact_email_ciphertext",
                "phone_number_key_id",
                "phone_number_nonce",
                "phone_number_ciphertext",
            )
        )
        assert web.get("/v1/auth/me", headers=headers).json()["account"]["profile_complete"] is True
        assert (
            web.post(
                "/v1/auth/sessions",
                headers={"Authorization": f"Bearer {assertion}"},
            ).status_code
            == 401
        )
        assert web.delete("/v1/auth/sessions/current", headers=headers).status_code == 204
        assert web.get("/v1/profiles/me", headers=headers).status_code == 401


def test_dob_collection_gate_allows_basic_profile_but_blocks_dob() -> None:
    settings, private_key = make_settings(enabled=False)
    mongo = FakeMongoClient()
    app = create_app(
        settings=settings,
        mongo_client_factory=lambda uri: cast(AsyncMongoClient, mongo),
        initialize_indexes=False,
    )

    with TestClient(app) as web:
        app.state.phase1_writes_ready = True
        login = web.post(
            "/v1/auth/sessions",
            headers={"Authorization": f"Bearer {make_assertion(private_key)}"},
        )
        token = login.json()["session_token"]
        basic_profile = web.patch(
            "/v1/profiles/me",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "profile_owner",
                "display_name": "Profile Owner",
                "cover_alt_text": "",
            },
        )
        assert basic_profile.status_code == 200
        assert basic_profile.json()["profile"]["date_of_birth"] is None
        assert not mongo.database["consent_events"].documents

        dob_profile = web.patch(
            "/v1/profiles/me",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": "profile_owner",
                "display_name": "Profile Owner",
                "date_of_birth": "1998-03-14",
                "cover_alt_text": "",
            },
        )
        assert dob_profile.status_code == 503
        stored = next(iter(mongo.database["profiles"].documents.values()))
        assert not any(key.startswith("dob_") for key in stored)
