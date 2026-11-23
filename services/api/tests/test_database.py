import pytest

from app.database import ensure_foundation_indexes


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
