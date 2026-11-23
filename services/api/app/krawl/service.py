"""Krawl event recording and temporary ban decisions."""

import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_hex
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError
from starlette.responses import PlainTextResponse

from app.client_identity import IPAddress, hash_client_ip
from app.config import Settings

logger = logging.getLogger("ahoya.krawl")
DECOY_PATHS = frozenset(
    {
        "/admin",
        "/wp-admin",
        "/phpmyadmin",
        "/.env",
        "/.aws/credentials",
        "/config.php",
    }
)


@dataclass(frozen=True)
class ProbeResult:
    client_ip_hash: str | None
    hit_count: int | None
    banned_until: datetime | None


def should_ban(hit_count: int, threshold: int) -> bool:
    """Return whether repeated decoy probes reach the configured threshold."""
    return hit_count >= threshold


def counter_bucket_id(client_ip_hash: str, now: datetime, window_seconds: int) -> str:
    """Return a deterministic fixed-window counter key."""
    bucket = int(now.timestamp()) // window_seconds
    return f"{client_ip_hash}:{bucket}"


class KrawlService:
    """Record decoy probes and maintain a short-lived source ban list."""

    def __init__(self, database: AsyncDatabase[dict[str, object]], settings: Settings) -> None:
        self.events = database["security_events"]
        self.bans = database["krawl_bans"]
        self.counters = database["krawl_counters"]
        self.settings = settings
        self.secret = settings.krawl_hmac_secret.get_secret_value().encode("utf-8")

    async def record_probe(
        self,
        path: str,
        client_ip: IPAddress | None,
        request_id: str,
        now: datetime | None = None,
    ) -> ProbeResult:
        """Store a sanitised event and update an atomic counter if identity is trusted."""
        observed_at = now or datetime.now(UTC)
        identity = hash_client_ip(client_ip, self.secret) if client_ip else None
        event: dict[str, object] = {
            "event_id": str(uuid4()),
            "event_type": "decoy_probe",
            "path": path,
            "request_id": request_id,
            "observed_at": observed_at,
            "client_ip_hash": identity,
        }

        try:
            await self.events.insert_one(event)
            if identity is None:
                return ProbeResult(None, None, None)

            bucket_id = counter_bucket_id(identity, observed_at, self.settings.krawl_window_seconds)
            bucket_end = datetime.fromtimestamp(
                (int(observed_at.timestamp()) // self.settings.krawl_window_seconds + 1)
                * self.settings.krawl_window_seconds,
                UTC,
            )
            counter = await self.counters.find_one_and_update(
                {"_id": bucket_id},
                {
                    "$inc": {"hit_count": 1},
                    "$setOnInsert": {
                        "expires_at": bucket_end
                        + timedelta(seconds=self.settings.krawl_window_seconds)
                    },
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            stored_hit_count = counter.get("hit_count") if counter else None
            hit_count = stored_hit_count if isinstance(stored_hit_count, int) else 0
            if not should_ban(hit_count, self.settings.krawl_ban_threshold):
                return ProbeResult(identity, hit_count, None)

            banned_until = observed_at + timedelta(seconds=self.settings.krawl_ban_seconds)
            with suppress(DuplicateKeyError):
                await self.bans.update_one(
                    {
                        "_id": identity,
                        "$or": [
                            {"banned_until": {"$lte": observed_at}},
                            {"banned_until": {"$exists": False}},
                        ],
                    },
                    {
                        "$set": {"banned_until": banned_until, "expires_at": banned_until},
                        "$setOnInsert": {"created_at": observed_at},
                    },
                    upsert=True,
                )
            return ProbeResult(identity, hit_count, banned_until)
        except PyMongoError as exc:
            logger.warning(
                "krawl_record_failed",
                extra={"error_type": type(exc).__name__},
            )
            return ProbeResult(identity, None, None)

    async def is_banned(self, client_ip: IPAddress) -> bool:
        """Check the live ban window without relying on asynchronous TTL cleanup."""
        identity = hash_client_ip(client_ip, self.secret)
        now = datetime.now(UTC)
        try:
            return (
                await self.bans.find_one(
                    {"_id": identity, "banned_until": {"$gt": now}},
                    projection={"_id": 1},
                )
                is not None
            )
        except PyMongoError as exc:
            logger.warning(
                "krawl_ban_check_failed",
                extra={"error_type": type(exc).__name__},
            )
            raise


def decoy_response(path: str) -> PlainTextResponse:
    """Return inert, variable decoy text without exposing real configuration."""
    nonce = token_hex(12)
    if path == "/.env":
        content = f"APP_ENV=production\nAPI_KEY=decoy-{nonce}\n"
    elif path == "/.aws/credentials":
        content = f"[default]\naws_access_key_id=DECOY{nonce}\n"
    else:
        content = f"Resource unavailable\nReference: {nonce}\n"
    return PlainTextResponse(
        content,
        status_code=404,
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )
