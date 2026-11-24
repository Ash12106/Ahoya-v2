"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from app.account.routes import router as account_router
from app.auth.routes import router as auth_router
from app.config import Settings
from app.consents.routes import router as consents_router
from app.database import (
    ensure_foundation_indexes,
    ensure_phase1_indexes,
    supports_phase1_transactions,
)
from app.errors import http_error_handler, unexpected_error_handler, validation_error_handler
from app.health import router as health_router
from app.krawl.middleware import KrawlMiddleware
from app.krawl.service import KrawlService
from app.logging_config import configure_logging
from app.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.profiles.routes import router as profiles_router

logger = logging.getLogger("ahoya.startup")
MongoClientFactory = Callable[[str], AsyncMongoClient[dict[str, object]]]


def create_app(
    settings: Settings | None = None,
    mongo_client_factory: MongoClientFactory | None = None,
    initialize_indexes: bool = True,
) -> FastAPI:
    """Create an API app with its MongoDB lifecycle and security boundaries."""
    resolved_settings = settings or Settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = (
            mongo_client_factory(resolved_settings.mongodb_uri.get_secret_value())
            if mongo_client_factory
            else AsyncMongoClient(
                resolved_settings.mongodb_uri.get_secret_value(),
                serverSelectionTimeoutMS=resolved_settings.mongo_server_selection_timeout_ms,
                connectTimeoutMS=resolved_settings.mongo_server_selection_timeout_ms,
            )
        )
        database = client[resolved_settings.database_name]
        app.state.mongo_client = client
        app.state.database = database
        app.state.settings = resolved_settings
        app.state.krawl = KrawlService(database, resolved_settings)
        app.state.phase1_writes_ready = False
        try:
            try:
                await client.admin.command({"ping": 1})
                if initialize_indexes:
                    app.state.phase1_writes_ready = await supports_phase1_transactions(
                        client,
                        database,
                    )
                    await ensure_foundation_indexes(
                        database,
                        resolved_settings.security_event_retention_days,
                    )
                    if app.state.phase1_writes_ready:
                        await ensure_phase1_indexes(database)
            except PyMongoError as exc:
                app.state.phase1_writes_ready = False
                logger.error(
                    "database_startup_check_failed",
                    extra={"error_type": type(exc).__name__},
                )
            yield
        finally:
            await client.close()

    middleware = [
        Middleware(RequestIdMiddleware),
        Middleware(
            SecurityHeadersMiddleware,
            app_env=resolved_settings.app_env,
        ),
        Middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        ),
        Middleware(KrawlMiddleware, settings=resolved_settings),
    ]
    app = FastAPI(
        title="Ahoya API",
        version="0.1.0",
        docs_url=None if resolved_settings.app_env == "production" else "/docs",
        redoc_url=None if resolved_settings.app_env == "production" else "/redoc",
        openapi_url=None if resolved_settings.app_env == "production" else "/openapi.json",
        lifespan=lifespan,
        middleware=middleware,
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(consents_router)
    app.include_router(profiles_router)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    return app
