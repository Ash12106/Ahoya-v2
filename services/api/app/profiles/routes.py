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
from app.auth.security import (
    decrypt_date_of_birth,
    decrypt_profile_contact,
    encrypt_date_of_birth,
    encrypt_profile_contact,
)

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
    contact_email: str | None = Field(default=None, max_length=254)
    phone_number: str | None = Field(default=None, max_length=32)

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

    @field_validator("contact_email", mode="before")
    @classmethod
    def normalize_contact_email(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Contact email must be text")
        value = value.strip()
        if not value:
            return None
        if len(value) > 254 or value.count("@") != 1:
            raise ValueError("Contact email is invalid")
        local, _, domain = value.partition("@")
        if (
            not local
            or len(local) > 64
            or local.startswith(".")
            or local.endswith(".")
            or ".." in local
            or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~.-]+", local)
        ):
            raise ValueError("Contact email is invalid")
        try:
            normalized_domain = domain.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("Contact email is invalid") from exc
        labels = normalized_domain.split(".")
        if (
            len(normalized_domain) > 253
            or len(labels) < 2
            or any(
                not label
                or len(label) > 63
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in labels
            )
        ):
            raise ValueError("Contact email is invalid")
        return f"{local}@{normalized_domain}"

    @field_validator("phone_number", mode="before")
    @classmethod
    def normalize_phone_number(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Phone number must be text")
        compact = re.sub(r"[\s()-]", "", value)
        if not compact:
            return None
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", compact):
            raise ValueError("Phone number must use international format")
        return compact


def contact_email_changes_remaining(history: object, now: datetime | None = None) -> int:
    """Return the owner's remaining contact email changes in a rolling week."""
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=7)
    if not isinstance(history, list):
        return 2
    recent_changes = [
        timestamp
        for item in history
        if (timestamp := as_utc_datetime(item)) is not None and timestamp > cutoff
    ]
    return max(0, 2 - len(recent_changes))


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
            "contact_email_changes_remaining": 2,
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
        contact_email = decrypt_profile_contact(
            profile, "contact_email", user.user_id, request.app.state.settings
        )
        phone_number = decrypt_profile_contact(
            profile, "phone_number", user.user_id, request.app.state.settings
        )
    except ValueError as exc:
        logger.error("profile_pii_decrypt_failed", extra={"field": "profile_contact"})
        raise HTTPException(status_code=503) from exc
    updated_at = profile.get("updated_at")
    return {
        "profile": {
            "username": profile.get("username"),
            "display_name": profile.get("display_name"),
            "date_of_birth": dob.isoformat() if dob is not None else None,
            "cover_alt_text": profile.get("cover_alt_text", ""),
            "contact_email": contact_email,
            "phone_number": phone_number,
            "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
        },
        "contact_email_changes_remaining": contact_email_changes_remaining(
            profile.get("contact_email_change_history")
        ),
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

            contact_email_field_set = "contact_email" in payload.model_fields_set
            phone_number_field_set = "phone_number" in payload.model_fields_set
            existing_contact_email = (
                decrypt_profile_contact(existing_profile, "contact_email", user.user_id, settings)
                if existing_profile is not None
                else None
            )
            existing_phone_number = (
                decrypt_profile_contact(existing_profile, "phone_number", user.user_id, settings)
                if existing_profile is not None
                else None
            )
            contact_email_history: list[datetime] = []
            if existing_profile is not None:
                history = existing_profile.get("contact_email_change_history", [])
                if isinstance(history, list):
                    cutoff = now - timedelta(days=7)
                    contact_email_history = [
                        timestamp
                        for item in history
                        if (timestamp := as_utc_datetime(item)) is not None and timestamp > cutoff
                    ]
            contact_email_changed = (
                contact_email_field_set and payload.contact_email != existing_contact_email
            )
            has_contact_email_history = bool(
                existing_profile
                and (
                    any(
                        key in existing_profile
                        for key in (
                            "contact_email_key_id",
                            "contact_email_nonce",
                            "contact_email_ciphertext",
                        )
                    )
                    or existing_profile.get("contact_email_change_history")
                )
            )
            if (
                contact_email_changed
                and payload.contact_email is not None
                and has_contact_email_history
            ):
                if len(contact_email_history) >= 2:
                    retry_after = max(
                        1,
                        int((min(contact_email_history) + timedelta(days=7) - now).total_seconds()),
                    )
                    raise HTTPException(
                        status_code=429,
                        detail="contact_email_change_limit",
                        headers={"Retry-After": str(retry_after)},
                    )
                contact_email_history.append(now)

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
            profile_updates: dict[str, Any] = {
                "username": payload.username,
                "username_change_history": recent_username_changes,
                "display_name": payload.display_name,
                "cover_alt_text": payload.cover_alt_text,
                "user_id": user.user_id,
                "contact_email_change_history": contact_email_history,
                **encrypted_dob,
                "updated_at": now,
            }
            profile_unsets: dict[str, str] = {}
            if contact_email_field_set:
                if payload.contact_email is None:
                    profile_unsets.update(
                        {
                            f"contact_email_{suffix}": ""
                            for suffix in ("key_id", "nonce", "ciphertext")
                        }
                    )
                else:
                    profile_updates.update(
                        encrypt_profile_contact(
                            payload.contact_email,
                            "contact_email",
                            user.user_id,
                            settings,
                        )
                    )
            if phone_number_field_set:
                if payload.phone_number is None:
                    profile_unsets.update(
                        {
                            f"phone_number_{suffix}": ""
                            for suffix in ("key_id", "nonce", "ciphertext")
                        }
                    )
                else:
                    profile_updates.update(
                        encrypt_profile_contact(
                            payload.phone_number,
                            "phone_number",
                            user.user_id,
                            settings,
                        )
                    )
            stored_contact_email = (
                payload.contact_email if contact_email_field_set else existing_contact_email
            )
            stored_phone_number = (
                payload.phone_number if phone_number_field_set else existing_phone_number
            )
            await database["profiles"].update_one(
                {"user_id": user.user_id},
                {
                    "$set": profile_updates,
                    "$setOnInsert": {"created_at": now},
                    **({"$unset": profile_unsets} if profile_unsets else {}),
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
        logger.error("profile_pii_protection_failed", extra={"field": "profile_personal_data"})
        raise HTTPException(status_code=503) from exc

    response.headers["Cache-Control"] = "private, no-store"
    return {
        "profile": {
            "username": payload.username,
            "display_name": payload.display_name,
            "cover_alt_text": payload.cover_alt_text,
            "date_of_birth": stored_dob.isoformat() if stored_dob is not None else None,
            "contact_email": stored_contact_email,
            "phone_number": stored_phone_number,
            "updated_at": now.isoformat(),
        },
        "contact_email_changes_remaining": contact_email_changes_remaining(
            contact_email_history, now
        ),
    }
