import base64
import json
from datetime import UTC, date, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.auth.security import (
    InvalidAssertion,
    assertion_replay_hash,
    decrypt_date_of_birth,
    encrypt_date_of_birth,
    new_session_token,
    session_token_hash,
    verify_web_assertion,
)
from app.config import Settings
from app.consents.routes import ConsentInput
from app.profiles.routes import ProfileUpdate


def make_settings(
    signer: Ed25519PrivateKey | None = None,
    pii_key: bytes = b"k" * 32,
) -> tuple[Settings, Ed25519PrivateKey]:
    signer = signer or Ed25519PrivateKey.generate()
    public_der = signer.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        mongodb_uri="mongodb://localhost:27017",
        database_name="ahoya_test",
        krawl_hmac_secret="t" * 40,
        web_assertion_public_keys=json.dumps({"test-key": base64.b64encode(public_der).decode()}),
        pii_encryption_keys=json.dumps({"test-pii": base64.b64encode(pii_key).decode()}),
        pii_encryption_active_key_id="test-pii",
    )
    return settings, signer


def make_assertion(
    private_key: Ed25519PrivateKey,
    *,
    audience: str = "ahoya-api",
    algorithm: str = "EdDSA",
    issued_at: datetime | None = None,
    lifetime_seconds: int = 60,
) -> str:
    now = issued_at or datetime.now(UTC)
    issued_timestamp = int(now.timestamp())
    return jwt.encode(
        {
            "iss": "ahoya-web",
            "aud": audience,
            "sub": "google-subject-for-test-only",
            "provider": "google",
            "jti": "a" * 64,
            "iat": issued_timestamp,
            "exp": issued_timestamp + lifetime_seconds,
        },
        private_key if algorithm == "EdDSA" else "test-secret-for-invalid-algorithm",
        algorithm=algorithm,
        headers={"kid": "test-key", "typ": "JWT"},
    )


def test_web_assertion_requires_signature_issuer_audience_and_short_lifetime() -> None:
    settings, private_key = make_settings()
    token = make_assertion(private_key)

    verified = verify_web_assertion(token, settings)

    assert verified.google_subject == "google-subject-for-test-only"
    assert verified.replay_id == "a" * 64
    assert verified.expires_at > datetime.now(UTC)


@pytest.mark.parametrize(
    "options",
    [
        {"audience": "other-service"},
        {"algorithm": "HS256"},
        {"lifetime_seconds": 61},
        {"issued_at": datetime.now(UTC) - timedelta(seconds=120)},
    ],
)
def test_web_assertion_rejects_invalid_claims_and_algorithm(options: dict[str, object]) -> None:
    settings, private_key = make_settings()

    with pytest.raises(InvalidAssertion):
        verify_web_assertion(make_assertion(private_key, **options), settings)


def test_date_of_birth_is_encrypted_and_bound_to_the_owner() -> None:
    settings, _ = make_settings()
    value = date(1990, 4, 5)

    stored = encrypt_date_of_birth(value, "owner-one", settings)

    assert value.isoformat() not in json.dumps(stored)
    assert decrypt_date_of_birth(stored, "owner-one", settings) == value
    with pytest.raises(ValueError):
        decrypt_date_of_birth(stored, "owner-two", settings)


def test_session_tokens_are_random_and_only_hashes_are_stored() -> None:
    first = new_session_token()
    second = new_session_token()

    assert len(first) >= 43
    assert first != second
    assert session_token_hash(first) != first
    assert session_token_hash(first) == session_token_hash(first)
    assert assertion_replay_hash("random-jti") != "random-jti"


def test_profile_input_rejects_unapproved_fields_and_future_dates() -> None:
    valid = {
        "username": "Aashish",
        "display_name": "Aashish",
        "date_of_birth": "2000-01-02",
    }
    profile = ProfileUpdate.model_validate(valid)

    assert profile.display_name == "Aashish"
    assert profile.date_of_birth == date(2000, 1, 2)
    with pytest.raises(ValueError):
        ProfileUpdate.model_validate({**valid, "user_id": "another-user"})
    with pytest.raises(ValueError):
        ProfileUpdate.model_validate(
            {**valid, "date_of_birth": (datetime.now(UTC).date() + timedelta(days=1)).isoformat()}
        )
    with pytest.raises(ValueError):
        ProfileUpdate.model_validate({**valid, "date_of_birth": "2000-1-2"})
    with pytest.raises(ValueError):
        ProfileUpdate.model_validate({**valid, "date_of_birth": "2000-02-30"})
    with pytest.raises(ValueError):
        ProfileUpdate.model_validate({**valid, "date_of_birth_consent": True})


def test_profile_input_allows_basic_profile_without_date_of_birth() -> None:
    profile = ProfileUpdate.model_validate(
        {"username": "Aashish", "display_name": "Aashish", "cover_alt_text": ""}
    )

    assert profile.date_of_birth is None


def test_consent_requires_supported_purpose_and_explicit_acceptance() -> None:
    valid = {
        "purpose": "self_declared_date_of_birth",
        "notice_version": "notice-v1",
        "consented": True,
    }

    assert ConsentInput.model_validate(valid).consented is True
    with pytest.raises(ValueError):
        ConsentInput.model_validate({**valid, "consented": False})
