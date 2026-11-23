from ipaddress import ip_address

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app.config import Settings
from app.krawl.service import DECOY_PATHS, KrawlService, decoy_response


class MemoryCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []
        self.count = 0
        self.error: Exception | None = None

    async def insert_one(self, document: dict[str, object]) -> None:
        if self.error:
            raise self.error
        self.documents.append(document)

    async def find_one_and_update(
        self,
        query: dict[str, object],
        update: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        if self.error:
            raise self.error
        self.count += int(update["$inc"]["hit_count"])
        return {"hit_count": self.count}

    async def update_one(
        self,
        query: dict[str, object],
        update: dict[str, object],
        **kwargs: object,
    ) -> None:
        if self.error:
            raise self.error
        self.documents.append(update)

    async def find_one(
        self,
        query: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object] | None:
        if self.error:
            raise self.error
        if self.documents:
            return {"_id": query["_id"]}
        return None


class MemoryDatabase:
    def __init__(self) -> None:
        self.collections = {
            "security_events": MemoryCollection(),
            "krawl_bans": MemoryCollection(),
            "krawl_counters": MemoryCollection(),
        }

    def __getitem__(self, name: str) -> MemoryCollection:
        return self.collections[name]


def make_service(threshold: int = 2) -> tuple[KrawlService, MemoryDatabase]:
    database = MemoryDatabase()
    settings = Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri="mongodb://localhost:27017",
        database_name="ahoya_test",
        krawl_hmac_secret="k" * 40,
        krawl_ban_threshold=threshold,
    )
    return KrawlService(database, settings), database


@pytest.mark.asyncio
async def test_repeated_probes_are_hashed_and_create_a_temporary_ban() -> None:
    service, database = make_service()
    source_ip = ip_address("192.0.2.18")

    first = await service.record_probe("/.env", source_ip, "request-one")
    second = await service.record_probe("/wp-admin", source_ip, "request-two")

    assert first.hit_count == 1
    assert first.banned_until is None
    assert second.hit_count == 2
    assert second.banned_until is not None
    assert await service.is_banned(source_ip)
    event = database["security_events"].documents[0]
    assert event["path"] == "/.env"
    assert event["observed_at"]
    assert event["client_ip_hash"] != str(source_ip)
    assert len(database["security_events"].documents) == 2


@pytest.mark.asyncio
async def test_untrusted_probe_records_event_without_creating_a_counter() -> None:
    service, database = make_service()

    result = await service.record_probe("/admin", None, "request-one")

    assert result.client_ip_hash is None
    assert result.hit_count is None
    assert result.banned_until is None
    assert database["security_events"].documents[0]["client_ip_hash"] is None
    assert database["krawl_counters"].count == 0


@pytest.mark.asyncio
async def test_probe_database_error_does_not_escape_or_log_probe_data() -> None:
    service, database = make_service()
    database["security_events"].error = ServerSelectionTimeoutError("private connection detail")

    result = await service.record_probe("/.env", ip_address("192.0.2.18"), "request-one")

    assert result.hit_count is None
    assert result.banned_until is None


@pytest.mark.asyncio
async def test_ban_lookup_failure_is_raised_for_fail_closed_middleware() -> None:
    service, database = make_service()
    database["krawl_bans"].error = ServerSelectionTimeoutError("private connection detail")

    with pytest.raises(ServerSelectionTimeoutError):
        await service.is_banned(ip_address("192.0.2.18"))


def test_decoy_paths_are_exact_and_responses_are_non_cacheable() -> None:
    assert "/admin" in DECOY_PATHS
    assert "/admin/users" not in DECOY_PATHS

    response = decoy_response("/.env")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert "decoy-" in response.body.decode()
