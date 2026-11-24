"""Shared, TTL-backed rate limits for authenticated API requests."""

import hashlib
import hmac
import logging
import math
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.config import Settings

logger = logging.getLogger("ahoya.rate_limit")


async def enforce_shared_rate_limit(
    database: AsyncDatabase[dict[str, object]],
    settings: Settings,
    scope: str,
    identity: str,
    *,
    limit: int,
    window_seconds: int,
    now: datetime | None = None,
) -> None:
    """Count requests atomically in MongoDB and fail closed if the store is unavailable."""
    current_time = now or datetime.now(UTC)
    bucket = int(current_time.timestamp()) // window_seconds
    bucket_end = datetime.fromtimestamp((bucket + 1) * window_seconds, UTC)
    identity_hash = hmac.new(
        settings.krawl_hmac_secret.get_secret_value().encode("utf-8"),
        f"{scope}:{identity}".encode(),
        hashlib.sha256,
    ).hexdigest()
    counter_id = f"api-rate:{scope}:{identity_hash}:{bucket}"
    expires_at = bucket_end + timedelta(seconds=window_seconds)

    try:
        counter = await database["krawl_counters"].find_one_and_update(
            {"_id": counter_id},
            {
                "$inc": {"hit_count": 1},
                "$setOnInsert": {"expires_at": expires_at},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except PyMongoError as exc:
        logger.warning(
            "api_rate_limit_store_failed",
            extra={"scope": scope, "error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503) from exc

    hit_count = counter.get("hit_count") if counter is not None else None
    if not isinstance(hit_count, int) or isinstance(hit_count, bool):
        raise HTTPException(status_code=503)
    if hit_count > limit:
        retry_after = max(1, math.ceil((bucket_end - current_time).total_seconds()))
        raise HTTPException(status_code=429, headers={"Retry-After": str(retry_after)})
