import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException
from pymongo.errors import AutoReconnect

from app.config import Settings
from app.rate_limit import enforce_shared_rate_limit


class CounterCollection:
    def __init__(self, *, fail: bool = False) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.fail = fail

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool,
        return_document: object,
    ) -> dict[str, Any] | None:
        del return_document
        if self.fail:
            raise AutoReconnect("test database unavailable")
        counter_id = str(query["_id"])
        document = self.documents.get(counter_id)
        if document is None:
            if not upsert:
                return None
            document = {"_id": counter_id}
            self.documents[counter_id] = document
            document.update(update.get("$setOnInsert", {}))
        for field, amount in update.get("$inc", {}).items():
            document[field] = document.get(field, 0) + amount
        return dict(document)


class CounterDatabase:
    def __init__(self, collection: CounterCollection) -> None:
        self.collection = collection

    def __getitem__(self, name: str) -> CounterCollection:
        assert name == "krawl_counters"
        return self.collection


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri="mongodb://localhost:27017",
        database_name="ahoya_test",
        krawl_hmac_secret="r" * 40,
    )


@pytest.mark.asyncio
async def test_shared_rate_limit_hashes_identity_and_returns_retry_after() -> None:
    collection = CounterCollection()
    database = CounterDatabase(collection)
    settings = make_settings()
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)

    await enforce_shared_rate_limit(
        database,
        settings,
        "auth-session",
        "google-subject-private",
        limit=1,
        window_seconds=900,
        now=now,
    )
    with pytest.raises(HTTPException) as raised:
        await enforce_shared_rate_limit(
            database,
            settings,
            "auth-session",
            "google-subject-private",
            limit=1,
            window_seconds=900,
            now=now,
        )

    assert raised.value.status_code == 429
    assert raised.value.headers is not None
    assert raised.value.headers["Retry-After"] == "900"
    stored = json.dumps(collection.documents, default=str)
    assert "google-subject-private" not in stored
    assert len(collection.documents) == 1


@pytest.mark.asyncio
async def test_rate_limit_counters_are_scoped_and_database_errors_fail_closed() -> None:
    collection = CounterCollection()
    database = CounterDatabase(collection)
    settings = make_settings()
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)

    await enforce_shared_rate_limit(
        database,
        settings,
        "auth-session",
        "subject-one",
        limit=1,
        window_seconds=900,
        now=now,
    )
    await enforce_shared_rate_limit(
        database,
        settings,
        "auth-session",
        "subject-two",
        limit=1,
        window_seconds=900,
        now=now,
    )

    assert len(collection.documents) == 2
    with pytest.raises(HTTPException) as raised:
        await enforce_shared_rate_limit(
            CounterDatabase(CounterCollection(fail=True)),
            settings,
            "auth-session",
            "subject-three",
            limit=1,
            window_seconds=900,
            now=now,
        )
    assert raised.value.status_code == 503
