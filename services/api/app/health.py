"""Liveness and MongoDB readiness endpoints."""

import logging

from fastapi import APIRouter, Request
from pymongo.errors import PyMongoError
from starlette.responses import JSONResponse

from app.errors import error_body

logger = logging.getLogger("ahoya.health")
router = APIRouter()


@router.get("/health")
async def liveness(request: Request) -> dict[str, str]:
    """Report process liveness without depending on MongoDB."""
    return {"status": "ok", "request_id": request.state.request_id}


@router.get("/health/db", response_model=None)
async def database_health(request: Request) -> dict[str, str] | JSONResponse:
    """Ping MongoDB and return a generic dependency error on failure."""
    try:
        await request.app.state.mongo_client.admin.command({"ping": 1})
    except PyMongoError as exc:
        logger.warning(
            "database_health_failed",
            extra={"error_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=503,
            content=error_body(
                "DATABASE_UNAVAILABLE",
                "Database unavailable",
                request.state.request_id,
            ),
        )
    return {"status": "ok", "request_id": request.state.request_id}


@router.get("/health/phase1", response_model=None)
async def phase1_health(request: Request) -> dict[str, str] | JSONResponse:
    """Report whether the database has passed Phase 1's transaction preflight."""
    if not getattr(request.app.state, "phase1_writes_ready", False):
        return JSONResponse(
            status_code=503,
            content=error_body(
                "SERVICE_UNAVAILABLE",
                "Service temporarily unavailable",
                request.state.request_id,
            ),
        )
    return {"status": "ok", "request_id": request.state.request_id}
