import pytest

from app.database import (
    ensure_foundation_indexes,
    ensure_phase1_indexes,
    supports_phase1_transactions,
)


class IndexCollection:
    def __init__(self) -> None:
        self.indexes: list[object] = []

    async def create_indexes(self, indexes: list[object]) -> None:
        self.indexes = indexes


class IndexDatabase:
    def __init__(self) -> None:
        self.collections = {
            "security_events": IndexCollection(),
            "krawl_bans": IndexCollection(),
            "krawl_counters": IndexCollection(),
            "users": IndexCollection(),
            "auth_sessions": IndexCollection(),
            "auth_assertion_replays": IndexCollection(),
            "profiles": IndexCollection(),
            "consent_events": IndexCollection(),
        }

    def __getitem__(self, name: str) -> IndexCollection:
        return self.collections[name]


@pytest.mark.asyncio
async def test_foundation_indexes_include_retention_and_expiry_ttls() -> None:
    database = IndexDatabase()

    await ensure_foundation_indexes(database, 30)

    assert len(database["security_events"].indexes) == 3
    assert len(database["krawl_bans"].indexes) == 1
    assert len(database["krawl_counters"].indexes) == 1


@pytest.mark.asyncio
async def test_phase1_indexes_cover_unique_accounts_profiles_and_expiry() -> None:
    database = IndexDatabase()

    await ensure_phase1_indexes(database)

    assert len(database["users"].indexes) == 1
    assert len(database["auth_sessions"].indexes) == 3
    assert len(database["auth_assertion_replays"].indexes) == 1
    assert len(database["profiles"].indexes) == 2
    assert len(database["consent_events"].indexes) == 1


class PreflightTransaction:
    def __init__(self, state: dict[str, bool]) -> None:
        self.state = state

    async def __aenter__(self) -> "PreflightTransaction":
        self.state["started"] = True
        return self

    async def __aexit__(self, error_type: object, error: object, traceback: object) -> None:
        self.state["aborted"] = error_type is not None
        self.state["committed"] = error_type is None


class PreflightSession:
    def __init__(self, state: dict[str, bool]) -> None:
        self.state = state

    async def start_transaction(self, **kwargs: object) -> PreflightTransaction:
        del kwargs
        return PreflightTransaction(self.state)


class PreflightSessionContext:
    def __init__(self, state: dict[str, bool]) -> None:
        self.state = state

    async def __aenter__(self) -> PreflightSession:
        return PreflightSession(self.state)

    async def __aexit__(self, *args: object) -> None:
        return None


class PreflightCollection:
    def __init__(self, state: dict[str, bool]) -> None:
        self.state = state

    async def find_one(
        self, query: dict[str, object], projection: dict[str, int], session: object
    ) -> None:
        self.state["read_only_query"] = query == {} and projection == {"_id": 1}
        self.state["read_used_session"] = session is not None
        return None


class PreflightDatabase:
    def __init__(self, state: dict[str, bool]) -> None:
        self.state = state

    def __getitem__(self, name: str) -> PreflightCollection:
        assert name == "security_events"
        return PreflightCollection(self.state)


class PreflightAdmin:
    def __init__(self, topology: dict[str, object]) -> None:
        self.topology = topology

    async def command(self, command: dict[str, int]) -> dict[str, object]:
        assert command == {"hello": 1}
        return self.topology


class PreflightClient:
    def __init__(self, topology: dict[str, object], state: dict[str, bool]) -> None:
        self.admin = PreflightAdmin(topology)
        self.state = state

    def start_session(self) -> PreflightSessionContext:
        return PreflightSessionContext(self.state)


@pytest.mark.asyncio
async def test_transaction_preflight_reads_in_transaction_and_aborts_without_writing() -> None:
    state: dict[str, bool] = {}
    client = PreflightClient({"setName": "rs0"}, state)
    database = PreflightDatabase(state)

    supported = await supports_phase1_transactions(client, database)

    assert supported
    assert state["started"]
    assert state["read_only_query"]
    assert state["read_used_session"]
    assert state["aborted"]
    assert not state["committed"]


@pytest.mark.asyncio
async def test_transaction_preflight_disables_standalone_mongodb() -> None:
    state: dict[str, bool] = {}
    client = PreflightClient({"ok": 1}, state)
    database = PreflightDatabase(state)

    supported = await supports_phase1_transactions(client, database)

    assert not supported
    assert not state
