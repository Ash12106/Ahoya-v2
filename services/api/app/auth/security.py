"""Narrow JWT validation, session-token hashing and PII encryption helpers."""

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jwt import InvalidTokenError

from app.config import Settings

MAX_ASSERTION_LIFETIME_SECONDS = 60
ASSERTION_CLOCK_SKEW_SECONDS = 5
SESSION_LIFETIME_SECONDS = 7 * 24 * 60 * 60
KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
REPLAY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


class InvalidAssertion(ValueError):
    """Raised when the web service assertion is absent or invalid."""


@dataclass(frozen=True)
class WebAssertion:
    google_subject: str
    replay_id: str
    expires_at: datetime


def session_token_hash(token: str) -> str:
    """Hash a random bearer value before it is stored in MongoDB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def assertion_replay_hash(replay_id: str) -> str:
    """Hash a signed assertion's replay identifier before persistence."""
    return hashlib.sha256(replay_id.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    """Return a high-entropy opaque application-session token."""
    return secrets.token_urlsafe(48)


def _assertion_keys(settings: Settings) -> dict[str, Ed25519PublicKey]:
    try:
        raw: Any = json.loads(settings.web_assertion_public_keys)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidAssertion from exc
    if not isinstance(raw, dict) or not raw or len(raw) > 8:
        raise InvalidAssertion
    keys: dict[str, Ed25519PublicKey] = {}
    for key_id, encoded in raw.items():
        if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
            raise InvalidAssertion
        if not isinstance(encoded, str) or not encoded:
            raise InvalidAssertion
        try:
            der = base64.b64decode(encoded, validate=True)
            public_key = serialization.load_der_public_key(der)
        except (ValueError, TypeError) as exc:
            raise InvalidAssertion from exc
        if not isinstance(public_key, Ed25519PublicKey):
            raise InvalidAssertion
        keys[key_id] = public_key
    return keys


def verify_web_assertion(token: str, settings: Settings) -> WebAssertion:
    """Verify a short, single-use service assertion signed by the Next.js BFF."""
    if len(token) > 8192:
        raise InvalidAssertion
    try:
        header = jwt.get_unverified_header(token)
        if (
            set(header) != {"alg", "kid", "typ"}
            or header.get("alg") != "EdDSA"
            or header.get("typ") != "JWT"
            or not isinstance(header.get("kid"), str)
        ):
            raise InvalidAssertion
        key = _assertion_keys(settings).get(header["kid"])
        if key is None:
            raise InvalidAssertion
        claims = jwt.decode(
            token,
            key,
            algorithms=["EdDSA"],
            audience="ahoya-api",
            issuer="ahoya-web",
            leeway=ASSERTION_CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "jti", "sub"]},
        )
    except (InvalidTokenError, TypeError, KeyError) as exc:
        raise InvalidAssertion from exc

    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    replay_id = claims.get("jti")
    subject = claims.get("sub")
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at <= issued_at
        or expires_at - issued_at > MAX_ASSERTION_LIFETIME_SECONDS
        or issued_at > int(datetime.now(UTC).timestamp()) + ASSERTION_CLOCK_SKEW_SECONDS
        or not isinstance(replay_id, str)
        or not REPLAY_ID_PATTERN.fullmatch(replay_id)
        or not isinstance(subject, str)
        or not subject
        or len(subject) > 255
        or claims.get("provider") != "google"
    ):
        raise InvalidAssertion
    return WebAssertion(
        google_subject=subject,
        replay_id=replay_id,
        expires_at=datetime.fromtimestamp(expires_at, UTC),
    )


def _pii_keys(settings: Settings) -> dict[str, bytes]:
    try:
        raw: Any = json.loads(settings.pii_encryption_keys)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("PII encryption configuration is unavailable") from exc
    if not isinstance(raw, dict) or not raw or len(raw) > 8:
        raise ValueError("PII encryption configuration is unavailable")
    keys: dict[str, bytes] = {}
    for key_id, encoded in raw.items():
        if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
            raise ValueError("PII encryption configuration is invalid")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("PII encryption configuration is invalid")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("PII encryption configuration is invalid") from exc
        if len(decoded) != 32:
            raise ValueError("PII encryption configuration is invalid")
        keys[key_id] = decoded
    return keys


def encrypt_date_of_birth(value: date, user_id: str, settings: Settings) -> dict[str, str]:
    """Encrypt a date with AES-256-GCM and user/field-bound associated data."""
    keys = _pii_keys(settings)
    key_id = settings.pii_encryption_active_key_id
    key = keys.get(key_id)
    if key is None:
        raise ValueError("Active PII encryption key is unavailable")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        value.isoformat().encode("ascii"),
        f"{user_id}:date_of_birth".encode(),
    )
    return {
        "dob_key_id": key_id,
        "dob_nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        "dob_ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }


def decrypt_date_of_birth(document: dict[str, Any], user_id: str, settings: Settings) -> date:
    """Decrypt an owner-scoped DOB field without returning crypto error details."""
    keys = _pii_keys(settings)
    key_id = document.get("dob_key_id")
    nonce_value = document.get("dob_nonce")
    ciphertext_value = document.get("dob_ciphertext")
    if (
        not isinstance(key_id, str)
        or not isinstance(nonce_value, str)
        or not isinstance(ciphertext_value, str)
        or key_id not in keys
    ):
        raise ValueError("Stored date of birth is unavailable")
    try:
        nonce = base64.urlsafe_b64decode(nonce_value.encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(ciphertext_value.encode("ascii"))
        plaintext = AESGCM(keys[key_id]).decrypt(
            nonce,
            ciphertext,
            f"{user_id}:date_of_birth".encode(),
        )
        return date.fromisoformat(plaintext.decode("ascii"))
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Stored date of birth is unavailable") from exc


ContactField = Literal["contact_email", "phone_number"]


def encrypt_profile_contact(
    value: str, field: ContactField, user_id: str, settings: Settings
) -> dict[str, str]:
    """Encrypt a private contact value with owner- and field-bound AES-GCM data."""
    keys = _pii_keys(settings)
    key_id = settings.pii_encryption_active_key_id
    key = keys.get(key_id)
    if key is None:
        raise ValueError("Active PII encryption key is unavailable")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        value.encode("utf-8"),
        f"{user_id}:{field}".encode(),
    )
    return {
        f"{field}_key_id": key_id,
        f"{field}_nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
        f"{field}_ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    }


def decrypt_profile_contact(
    document: dict[str, Any], field: ContactField, user_id: str, settings: Settings
) -> str | None:
    """Decrypt a private contact field, rejecting partial or invalid ciphertext."""
    key_id = document.get(f"{field}_key_id")
    nonce_value = document.get(f"{field}_nonce")
    ciphertext_value = document.get(f"{field}_ciphertext")
    if key_id is None and nonce_value is None and ciphertext_value is None:
        return None
    keys = _pii_keys(settings)
    if (
        not isinstance(key_id, str)
        or not isinstance(nonce_value, str)
        or not isinstance(ciphertext_value, str)
        or key_id not in keys
    ):
        raise ValueError("Stored contact value is unavailable")
    try:
        nonce = base64.urlsafe_b64decode(nonce_value.encode("ascii"))
        ciphertext = base64.urlsafe_b64decode(ciphertext_value.encode("ascii"))
        plaintext = AESGCM(keys[key_id]).decrypt(
            nonce,
            ciphertext,
            f"{user_id}:{field}".encode(),
        )
        return plaintext.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Stored contact value is unavailable") from exc
