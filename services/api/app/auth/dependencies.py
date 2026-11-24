"""FastAPI dependencies for revocable application sessions."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import session_token_hash
from app.rate_limit import enforce_shared_rate_limit

bearer_scheme = HTTPBearer(auto_error=False)
SESSION_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


@dataclass(frozen=True)
class AuthenticatedUser:
    """The account and session resolved from the real database."""

    user_id: str
    session_hash: str
    session_id: str


async def require_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    """Resolve and validate a non-expired, non-revoked MongoDB session."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401)
    raw_token = credentials.credentials
    if not SESSION_TOKEN_PATTERN.fullmatch(raw_token):
        raise HTTPException(status_code=401)
    if not getattr(request.app.state, "phase1_writes_ready", False):
        raise HTTPException(status_code=503)

    token_hash = session_token_hash(raw_token)
    now = datetime.now(UTC)
    database = request.app.state.database
    session: dict[str, Any] | None = await database["auth_sessions"].find_one(
        {"_id": token_hash, "expires_at": {"$gt": now}, "revoked_at": {"$exists": False}},
        projection={"user_id": 1, "session_id": 1},
    )
    if (
        session is None
        or not isinstance(session.get("user_id"), str)
        or not isinstance(session.get("session_id"), str)
    ):
        raise HTTPException(status_code=401)
    user = await database["users"].find_one(
        {"_id": session["user_id"], "status": "active"},
        projection={"_id": 1},
    )
    if user is None:
        raise HTTPException(status_code=401)
    await enforce_shared_rate_limit(
        database,
        request.app.state.settings,
        "authenticated-api",
        session["user_id"],
        limit=120,
        window_seconds=60,
    )
    return AuthenticatedUser(
        user_id=session["user_id"],
        session_hash=token_hash,
        session_id=session["session_id"],
    )
