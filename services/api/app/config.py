"""Validated application configuration."""

from ipaddress import ip_network
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    mongodb_uri: SecretStr
    database_name: str = "ahoya"
    krawl_hmac_secret: SecretStr
    cloudflare_origin_token: SecretStr | None = None
    trusted_proxy_cidrs: str = ""
    cors_allowed_origins: str = "http://localhost:3000"
    krawl_ban_threshold: int = Field(default=3, ge=2, le=10)
    krawl_window_seconds: int = Field(default=600, ge=60, le=3600)
    krawl_ban_seconds: int = Field(default=86400, ge=86400, le=86400)
    krawl_tarpit_min_ms: int = Field(default=100, ge=100, le=500)
    krawl_tarpit_max_ms: int = Field(default=500, ge=100, le=500)
    security_event_retention_days: int = Field(default=30, ge=1, le=365)
    mongo_server_selection_timeout_ms: int = Field(default=2000, ge=250, le=10000)

    @field_validator("mongodb_uri")
    @classmethod
    def validate_mongodb_uri(cls, value: SecretStr) -> SecretStr:
        uri = value.get_secret_value()
        if not uri.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("MONGODB_URI must use mongodb:// or mongodb+srv://")
        return value

    @field_validator("database_name")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        if not value or any(character not in allowed for character in value):
            raise ValueError("DATABASE_NAME contains unsupported characters")
        return value

    @field_validator("krawl_hmac_secret")
    @classmethod
    def validate_krawl_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("KRAWL_HMAC_SECRET must contain at least 32 bytes")
        return value

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: str) -> str:
        items = [item.strip() for item in value.split(",") if item.strip()]
        for item in items:
            network = ip_network(item, strict=False)
            if network.prefixlen == 0:
                raise ValueError("TRUSTED_PROXY_CIDRS cannot trust every address")
        return ",".join(items)

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if not origins or "*" in origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit origins")
        normalized: list[str] = []
        for item in origins:
            parsed = urlsplit(item)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS_ALLOWED_ORIGINS entries must be exact HTTP origins")
            try:
                _ = parsed.port
            except ValueError as exc:
                raise ValueError("CORS_ALLOWED_ORIGINS contains an invalid port") from exc
            normalized.append(f"{parsed.scheme}://{parsed.netloc}")
        return ",".join(normalized)

    @field_validator("krawl_tarpit_max_ms")
    @classmethod
    def validate_tarpit_range(cls, value: int, info: ValidationInfo) -> int:
        minimum = info.data.get("krawl_tarpit_min_ms", 100)
        if value < minimum:
            raise ValueError("KRAWL_TARPIT_MAX_MS must be at least KRAWL_TARPIT_MIN_MS")
        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.app_env == "production":
            if not self.trusted_proxy_cidrs:
                raise ValueError("TRUSTED_PROXY_CIDRS is required in production")
            if (
                self.cloudflare_origin_token is None
                or len(self.cloudflare_origin_token.get_secret_value().encode("utf-8")) < 32
            ):
                raise ValueError("CLOUDFLARE_ORIGIN_TOKEN is required in production")
            local_hosts = {"localhost", "127.0.0.1", "::1"}
            if any(urlsplit(origin).hostname in local_hosts for origin in self.cors_origins):
                raise ValueError("Production CORS origins cannot include localhost")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

    @property
    def trusted_proxy_networks(self) -> tuple[str, ...]:
        return tuple(item for item in self.trusted_proxy_cidrs.split(",") if item)
