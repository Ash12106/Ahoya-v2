"""Server-to-server sign-in exchange and session revocation routes."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.auth.dependencies import AuthenticatedUser, bearer_scheme, require_user
from app.auth.security import (
    SESSION_LIFETIME_SECONDS,
    InvalidAssertion,
    assertion_replay_hash,
    new_session_token,
    session_token_hash,
    verify_web_assertion,
)
from app.rate_limit import enforce_shared_rate_limit

logger = logging.getLogger("ahoya.auth")
router = APIRouter(prefix="/v1/auth", tags=["authentication"])


@router.post("/sessions")
async def create_session(request: Request, response: Response) -> dict[str, object]:
    """Exchange a trusted web assertion for a server-side API session."""
    credentials: HTTPAuthorizationCredentials | None = await bearer_scheme(request)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401)
    if not getattr(request.app.state, "phase1_writes_ready", False):
        raise HTTPException(status_code=503)
    settings = request.app.state.settings
    try:
        assertion = verify_web_assertion(credentials.credentials, settings)
    except InvalidAssertion as exc:
        raise HTTPException(status_code=401) from exc
    await enforce_shared_rate_limit(
        request.app.state.database,
        settings,
        "auth-session",
        assertion.google_subject,
        limit=10,
        window_seconds=900,
    )

    now = datetime.now(UTC)
    session_expires_at = now + timedelta(seconds=SESSION_LIFETIME_SECONDS)
    api_token = new_session_token()
    token_hash = session_token_hash(api_token)
    session_id = uuid4().hex
    database = request.app.state.database
    client = request.app.state.mongo_client
    try:
        async with (
            client.start_session().bind() as mongo_session,
            await mongo_session.start_transaction(),
        ):
            await database["auth_assertion_replays"].insert_one(
                {
                    "_id": assertion_replay_hash(assertion.replay_id),
                    "expires_at": assertion.expires_at + timedelta(minutes=5),
                    "created_at": now,
                },
                session=mongo_session,
            )
            user = await database["users"].find_one_and_update(
                {"google_subject": assertion.google_subject},
                {
                    "$setOnInsert": {
                        "_id": uuid4().hex,
                        "google_subject": assertion.google_subject,
                        "status": "active",
                        "created_at": now,
                    },
                    "$set": {"last_login_at": now},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
                session=mongo_session,
            )
            if user is None or not isinstance(user.get("_id"), str):
                raise PyMongoError("Account lookup did not return a user")
            if user.get("status") != "active":
                raise HTTPException(status_code=403)
            await database["auth_sessions"].insert_one(
                {
                    "_id": token_hash,
                    "session_id": session_id,
                    "user_id": user["_id"],
                    "created_at": now,
                    "expires_at": session_expires_at,
                },
                session=mongo_session,
            )
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=401) from exc
    except PyMongoError as exc:
        logger.warning(
            "auth_session_create_failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503) from exc

    response.headers["Cache-Control"] = "private, no-store"
    return {
        "session_token": api_token,
        "expires_at": session_expires_at.isoformat(),
    }


@router.delete("/sessions/current", status_code=204)
async def revoke_session(
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> None:
    """Revoke the current application session in MongoDB."""
    try:
        await request.app.state.database["auth_sessions"].update_one(
            {"_id": user.session_hash, "revoked_at": {"$exists": False}},
            {"$set": {"revoked_at": datetime.now(UTC)}},
        )
    except PyMongoError as exc:
        logger.warning(
            "auth_session_revoke_failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=503) from exc
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/me")
async def get_current_account(
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, object]:
    """Return onboarding completion without exposing DOB or derived age."""
    profile = await request.app.state.database["profiles"].find_one(
        {"user_id": user.user_id},
        projection={
            "_id": 1,
            "username": 1,
            "dob_key_id": 1,
            "dob_nonce": 1,
            "dob_ciphertext": 1,
        },
    )
    has_encrypted_dob = profile is not None and all(
        key in profile for key in ("dob_key_id", "dob_nonce", "dob_ciphertext")
    )
    has_username = profile is not None and isinstance(profile.get("username"), str)
    profile_complete = (
        profile is not None
        and has_username
        and (not request.app.state.settings.dob_collection_enabled or has_encrypted_dob)
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "account": {
            "profile_complete": profile_complete,
        }
    }
