"""MongoDB startup checks and application indexes."""

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.collation import Collation
from pymongo.read_concern import ReadConcern


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


async def supports_phase1_transactions(
    client: AsyncMongoClient[dict[str, object]],
    database: AsyncDatabase[dict[str, object]],
) -> bool:
    """Prove transaction support using a read-only query and explicit abort."""
    topology = await client.admin.command({"hello": 1})
    if not topology.get("setName") and topology.get("msg") != "isdbgrid":
        return False

    class AbortReadOnlyPreflight(Exception):
        pass

    async with client.start_session() as session:
        try:
            async with await session.start_transaction(read_concern=ReadConcern("snapshot")):
                await database["security_events"].find_one(
                    {},
                    {"_id": 1},
                    session=session,
                )
                raise AbortReadOnlyPreflight
        except AbortReadOnlyPreflight:
            pass
    return True


async def ensure_phase1_indexes(database: AsyncDatabase[dict[str, object]]) -> None:
    """Create account, profile and consent indexes after transaction preflight."""
    await database["users"].create_indexes(
        [
            IndexModel(
                [("google_subject", ASCENDING)],
                unique=True,
                name="users_google_subject_unique",
            ),
        ]
    )
    await database["auth_sessions"].create_indexes(
        [
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="auth_sessions_expiry_ttl",
            ),
            IndexModel(
                [("user_id", ASCENDING), ("created_at", DESCENDING)],
                name="auth_sessions_user_created",
            ),
            IndexModel(
                [("session_id", ASCENDING)],
                unique=True,
                name="auth_sessions_session_id_unique",
            ),
        ]
    )
    await database["auth_assertion_replays"].create_indexes(
        [
            IndexModel(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="auth_assertion_replays_expiry_ttl",
            ),
        ]
    )
    await database["profiles"].create_indexes(
        [
            IndexModel(
                [("user_id", ASCENDING)],
                unique=True,
                name="profiles_user_unique",
            ),
            IndexModel(
                [("username", ASCENDING)],
                unique=True,
                collation=Collation(locale="en", strength=2),
                partialFilterExpression={"username": {"$type": "string"}},
                name="profiles_username_unique",
            ),
        ]
    )
    await database["consent_events"].create_indexes(
        [
            IndexModel(
                [("user_id", ASCENDING), ("consented_at", DESCENDING)],
                name="consent_events_user_time",
            ),
        ]
    )
