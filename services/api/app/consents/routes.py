"""Versioned, purpose-specific consent endpoints."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import PyMongoError

from app.auth.dependencies import AuthenticatedUser, require_user

router = APIRouter(prefix="/v1/consents", tags=["consents"])


class ConsentInput(BaseModel):
    """Accept only the reviewed date-of-birth consent purpose in this slice."""

    model_config = ConfigDict(extra="forbid")

    purpose: Literal["self_declared_date_of_birth"]
    notice_version: str = Field(min_length=1, max_length=64)
    consented: Literal[True]


@router.post("", status_code=201)
async def record_consent(
    payload: ConsentInput,
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> dict[str, bool]:
    """Persist consent before the corresponding personal data is accepted."""
    settings = request.app.state.settings
    if (
        not settings.dob_collection_enabled
        or payload.notice_version != settings.dob_collection_notice_version
    ):
        raise HTTPException(status_code=503)

    consented_at = datetime.now(UTC)
    try:
        client = request.app.state.mongo_client
        async with (
            client.start_session().bind() as mongo_session,
            await mongo_session.start_transaction(),
        ):
            await request.app.state.database["consent_events"].insert_one(
                {
                    "user_id": user.user_id,
                    "purpose": payload.purpose,
                    "scope": ["date_of_birth_storage", "age_eligibility_calculation"],
                    "notice_version": settings.dob_collection_notice_version,
                    "consented_at": consented_at,
                },
                session=mongo_session,
            )
    except PyMongoError as exc:
        raise HTTPException(status_code=503) from exc

    response.headers["Cache-Control"] = "private, no-store"
    return {"recorded": True}
