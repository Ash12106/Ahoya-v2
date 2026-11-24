"""Authenticated, MongoDB-backed account data export."""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pymongo.errors import PyMongoError

from app.auth.dependencies import AuthenticatedUser, require_user
from app.auth.security import decrypt_date_of_birth, decrypt_profile_contact
from app.config import Settings

logger = logging.getLogger("ahoya.account")
router = APIRouter(prefix="/v1/account", tags=["account"])


def _timestamp(value: object) -> str | None:
    """Serialize a stored MongoDB timestamp as an explicit UTC value."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _history_timestamps(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [timestamp for item in value if (timestamp := _timestamp(item)) is not None]


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _profile_export(profile: dict[str, Any], user_id: str, settings: Settings) -> dict[str, object]:
    has_dob = any(key in profile for key in ("dob_key_id", "dob_nonce", "dob_ciphertext"))
    date_of_birth = decrypt_date_of_birth(profile, user_id, settings) if has_dob else None
    return {
        "username": _optional_text(profile.get("username")),
        "display_name": _optional_text(profile.get("display_name")),
        "date_of_birth": date_of_birth.isoformat() if date_of_birth is not None else None,
        "contact_email": decrypt_profile_contact(profile, "contact_email", user_id, settings),
        "phone_number": decrypt_profile_contact(profile, "phone_number", user_id, settings),
        "cover_alt_text": _optional_text(profile.get("cover_alt_text")),
        "created_at": _timestamp(profile.get("created_at")),
        "updated_at": _timestamp(profile.get("updated_at")),
        "username_change_timestamps": _history_timestamps(profile.get("username_change_history")),
        "contact_email_change_timestamps": _history_timestamps(
            profile.get("contact_email_change_history")
        ),
    }


def _consent_export(event: dict[str, Any]) -> dict[str, object]:
    scope = event.get("scope")
    exported_scope = (
        [item for item in scope if isinstance(item, str)] if isinstance(scope, list) else []
    )
    return {
        "purpose": event.get("purpose") if isinstance(event.get("purpose"), str) else None,
        "scope": exported_scope,
        "notice_version": (
            event.get("notice_version") if isinstance(event.get("notice_version"), str) else None
        ),
        "provider_terms_version": (
            event.get("provider_terms_version")
            if isinstance(event.get("provider_terms_version"), str)
            else None
        ),
        "consented_at": _timestamp(event.get("consented_at")),
        "withdrawn_at": _timestamp(event.get("withdrawn_at")),
    }


@router.get("/export")
async def export_account_data(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> StreamingResponse:
    """Stream the caller's allowlisted account, profile, and consent data."""
    database = request.app.state.database
    try:
        account = await database["users"].find_one(
            {"_id": user.user_id, "status": "active"},
            projection={"_id": 0, "status": 1, "created_at": 1, "last_login_at": 1},
        )
        if account is None:
            raise HTTPException(status_code=401)
        profile = await database["profiles"].find_one(
            {"user_id": user.user_id},
            projection={"_id": 0, "user_id": 0},
        )
        profile_data = (
            _profile_export(profile, user.user_id, request.app.state.settings)
            if profile is not None
            else None
        )
        consent_cursor = (
            database["consent_events"]
            .find(
                {"user_id": user.user_id},
                projection={
                    "_id": 0,
                    "user_id": 0,
                    "purpose": 1,
                    "scope": 1,
                    "notice_version": 1,
                    "provider_terms_version": 1,
                    "consented_at": 1,
                    "withdrawn_at": 1,
                },
            )
            .sort("consented_at", 1)
        )
    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("account_export_pii_decrypt_failed", extra={"field": "profile"})
        raise HTTPException(status_code=503) from exc
    except PyMongoError as exc:
        logger.warning("account_export_read_failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503) from exc

    account_data = {
        "status": _optional_text(account.get("status")),
        "created_at": _timestamp(account.get("created_at")),
        "last_login_at": _timestamp(account.get("last_login_at")),
    }

    async def content() -> AsyncIterator[bytes]:
        yield b'{"format_version":1,"account":'
        yield _json_bytes(account_data)
        yield b',"profile":'
        yield _json_bytes(profile_data)
        yield b',"consents":['
        first = True
        try:
            async for event in consent_cursor:
                if not first:
                    yield b","
                yield _json_bytes(_consent_export(event))
                first = False
        except PyMongoError as exc:
            logger.warning("account_export_stream_failed", extra={"error_type": type(exc).__name__})
            raise
        finally:
            await consent_cursor.close()
        yield b"]}\n"

    return StreamingResponse(
        content(),
        media_type="application/json",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="ahoya-account-export.json"',
            "X-Content-Type-Options": "nosniff",
        },
    )
