"""MongoDB lifecycle and foundation indexes."""

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.database import AsyncDatabase


async def ensure_foundation_indexes(
    database: AsyncDatabase[dict[str, object]], retention_days: int
) -> None:
    """Create Krawl indexes idempotently for event lookup and expiry."""
    event_ttl_seconds = retention_days * 24 * 60 * 60
    await database["security_events"].create_indexes(
        [
            IndexModel(
                [("observed_at", ASCENDING)],
                expireAfterSeconds=event_ttl_seconds,
                name="security_events_retention_ttl",
            ),
            IndexModel(
                [("event_type", ASCENDING), ("observed_at", DESCENDING)],
                name="security_events_type_time",
            ),
            IndexModel(
                [("client_ip_hash", ASCENDING), ("observed_at", DESCENDING)],
                name="security_events_ip_time",
            ),
        ]
    )
    await database["krawl_bans"].create_indexes(
        [
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="krawl_bans_expiry_ttl",
            )
        ]
    )
    await database["krawl_counters"].create_indexes(
        [
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="krawl_counters_expiry_ttl",
            )
        ]
    )
