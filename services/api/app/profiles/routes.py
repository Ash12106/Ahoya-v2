"""Authenticated profile reads and updates backed by MongoDB."""

import logging
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.auth.dependencies import AuthenticatedUser, require_user
from app.auth.security import decrypt_date_of_birth, encrypt_date_of_birth

logger = logging.getLogger("ahoya.profiles")
router = APIRouter(prefix="/v1/profiles/me", tags=["profiles"])
MINIMUM_AGE_YEARS = 16


def meets_minimum_age(date_of_birth: date, today: date | None = None) -> bool:
    """Check age without returning or persisting a derived age value.

    Calendar comparison means leap-day birthdays reach the next age on March 1
    in non-leap years. Revisit this policy if legal review requires another rule.
    """
    current_date = today or datetime.now(UTC).date()
    age = current_date.year - date_of_birth.year
    if (current_date.month, current_date.day) < (date_of_birth.month, date_of_birth.day):
        age -= 1
    return age >= MINIMUM_AGE_YEARS


def as_utc_datetime(value: object) -> datetime | None:
    """Normalize a stored MongoDB timestamp for rolling-window comparisons."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ProfileUpdate(BaseModel):
    """Allowlisted fields a signed-in owner may set on their own profile."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=24, pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=80)
    date_of_birth: date | None = None
    cover_alt_text: str = Field(default="", max_length=250)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Username must be text")
        value = value.strip()
        if not value.isascii():
            raise ValueError("Username must use ASCII letters, numbers, or underscores")
        return value.lower()

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def require_iso_calendar_date(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Date of birth must use YYYY-MM-DD")
        return value

    @field_validator("display_name")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
            raise ValueError("Display name contains unsupported characters")
        return value

    @model_validator(mode="after")
    def validate_birth_date(self) -> "ProfileUpdate":
        if self.date_of_birth is not None:
            today = datetime.now(UTC).date()
            if self.date_of_birth >= today:
                raise ValueError("Date of birth must be in the past")
            if not meets_minimum_age(self.date_of_birth, today):
                raise ValueError("Ahoya accounts require a minimum age of 16")
        return self

    @field_validator("cover_alt_text")
    @classmethod
    def reject_alt_text_control_characters(cls, value: str) -> str:
        if any(unicodedata.category(character) in {"Cc", "Cs"} for character in value):
            raise ValueError("Cover description contains unsupported characters")
        return value


@router.get("")
async def get_profile(
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Return only the authenticated user's profile fields."""
    database = request.app.state.database
    profile = await database["profiles"].find_one(
        {"user_id": user.user_id},
        projection={"_id": 0},
    )
    response.headers["Cache-Control"] = "private, no-store"
    if profile is None:
        return {
            "profile": None,
            "date_of_birth_collection_enabled": request.app.state.settings.dob_collection_enabled,
            "minimum_age_years": MINIMUM_AGE_YEARS,
            "date_of_birth_consent_notice": (
                request.app.state.settings.dob_collection_notice_text
                if request.app.state.settings.dob_collection_enabled
                else None
            ),
            "date_of_birth_consent_notice_version": (
                request.app.state.settings.dob_collection_notice_version
                if request.app.state.settings.dob_collection_enabled
                else None
            ),
        }
    try:
        dob = (
            decrypt_date_of_birth(profile, user.user_id, request.app.state.settings)
            if any(key in profile for key in ("dob_key_id", "dob_nonce", "dob_ciphertext"))
            else None
        )
    except ValueError as exc:
        logger.error("profile_pii_decrypt_failed", extra={"field": "date_of_birth"})
        raise HTTPException(status_code=503) from exc
    updated_at = profile.get("updated_at")
    return {
        "profile": {
            "username": profile.get("username"),
            "display_name": profile.get("display_name"),
            "date_of_birth": dob.isoformat() if dob is not None else None,
            "cover_alt_text": profile.get("cover_alt_text", ""),
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
        },
        "date_of_birth_collection_enabled": request.app.state.settings.dob_collection_enabled,
        "minimum_age_years": MINIMUM_AGE_YEARS,
        "date_of_birth_consent_notice": (
            request.app.state.settings.dob_collection_notice_text
            if request.app.state.settings.dob_collection_enabled
            else None
        ),
        "date_of_birth_consent_notice_version": (
            request.app.state.settings.dob_collection_notice_version
            if request.app.state.settings.dob_collection_enabled
            else None
        ),
    }


@router.patch("")
async def update_profile(
    payload: ProfileUpdate,
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, Any]:
    """Persist an owner-submitted profile and its purpose-specific consent."""
    settings = request.app.state.settings
    if payload.date_of_birth is not None and (
        not settings.dob_collection_enabled or not settings.dob_collection_notice_version
    ):
        raise HTTPException(status_code=503)
    now = datetime.now(UTC)
    try:
        database = request.app.state.database
        client = request.app.state.mongo_client
        async with (
            client.start_session().bind() as mongo_session,
            await mongo_session.start_transaction(),
        ):
            existing_profile = await database["profiles"].find_one(
                {"user_id": user.user_id},
                projection={"_id": 0},
                session=mongo_session,
            )

            recent_username_changes: list[datetime] = []
            if existing_profile is not None:
                history = existing_profile.get("username_change_history", [])
                if isinstance(history, list):
                    cutoff = now - timedelta(days=7)
                    recent_username_changes = [
                        timestamp
                        for item in history
                        if (timestamp := as_utc_datetime(item)) is not None and timestamp > cutoff
                    ]
            existing_username = (
                existing_profile.get("username") if existing_profile is not None else None
            )
            username_changed = (
                isinstance(existing_username, str) and existing_username != payload.username
            )
            if username_changed and len(recent_username_changes) >= 2:
                retry_after = max(
                    1,
                    int((min(recent_username_changes) + timedelta(days=7) - now).total_seconds()),
                )
                raise HTTPException(
                    status_code=429,
                    detail="username_change_limit",
                    headers={"Retry-After": str(retry_after)},
                )
            if username_changed:
                recent_username_changes.append(now)

            has_encrypted_dob = existing_profile is not None and any(
                key in existing_profile for key in ("dob_key_id", "dob_nonce", "dob_ciphertext")
            )
            existing_dob = (
                decrypt_date_of_birth(existing_profile, user.user_id, settings)
                if has_encrypted_dob and existing_profile is not None
                else None
            )
            if (
                existing_dob is not None
                and payload.date_of_birth is not None
                and payload.date_of_birth != existing_dob
            ):
                raise HTTPException(status_code=409, detail="date_of_birth_locked")

            if payload.date_of_birth is not None and existing_dob is None:
                consent = await database["consent_events"].find_one(
                    {
                        "user_id": user.user_id,
                        "purpose": "self_declared_date_of_birth",
                        "notice_version": settings.dob_collection_notice_version,
                        "withdrawn_at": {"$exists": False},
                    },
                    session=mongo_session,
                )
                if consent is None:
                    raise HTTPException(status_code=403)

            stored_dob = existing_dob or payload.date_of_birth
            encrypted_dob = (
                encrypt_date_of_birth(payload.date_of_birth, user.user_id, settings)
                if payload.date_of_birth is not None and existing_dob is None
                else {}
            )
            if settings.dob_collection_enabled and (
                stored_dob is None or not meets_minimum_age(stored_dob)
            ):
                raise HTTPException(status_code=422)
            await database["profiles"].update_one(
                {"user_id": user.user_id},
                {
                    "$set": {
                        "username": payload.username,
                        "username_change_history": recent_username_changes,
                        "display_name": payload.display_name,
                        "cover_alt_text": payload.cover_alt_text,
                        "user_id": user.user_id,
                        **encrypted_dob,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
                session=mongo_session,
            )
    except DuplicateKeyError as exc:
        key_pattern = (exc.details or {}).get("keyPattern", {})
        username_conflict = isinstance(key_pattern, dict) and "username" in key_pattern
        logger.info(
            "profile_unique_conflict",
            extra={"conflict_field": "username" if username_conflict else "profile"},
        )
        raise HTTPException(
            status_code=409,
            detail="username_unavailable" if username_conflict else "profile_conflict",
        ) from exc
    except PyMongoError as exc:
        logger.warning(
            "profile_update_failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503) from exc
    except ValueError as exc:
        logger.error("profile_pii_protection_failed", extra={"field": "date_of_birth"})
        raise HTTPException(status_code=503) from exc

    response.headers["Cache-Control"] = "private, no-store"
    return {
        "profile": {
            "username": payload.username,
            "display_name": payload.display_name,
            "cover_alt_text": payload.cover_alt_text,
            "date_of_birth": stored_dob.isoformat() if stored_dob is not None else None,
            "updated_at": now.isoformat(),
        }
    }
