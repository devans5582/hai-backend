"""Typed settings from environment variables with the ``HAI_`` prefix.

Production refuses development secrets, secrets shorter than 32 characters and
``HAI_AUTH_DISABLED``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_PREFIX = "dev-"
MIN_SECRET_LENGTH = 32

# Allowed browser origins carried from legacy/express-api/server.js:14-24.
DEFAULT_CORS_ORIGINS = [
    "https://www.humaital.com",
    "https://humaital.com",
    "https://humanalignmentindex.com",
    "https://www.humanalignmentindex.com",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5500",
    "http://localhost:8080",
    "http://127.0.0.1",
    "http://127.0.0.1:5500",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HAI_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    service_name: str = "hai"

    # Database
    database_url: str = "postgresql://hai:hai@localhost:5432/hai"
    enforce_db_roles: bool = False
    migrations_dir: str = "db/migrations"

    # Auth
    auth_disabled: bool = False
    api_key_pepper: SecretStr = SecretStr("dev-api-key-pepper-not-for-production-0001")
    jwt_secret: SecretStr = SecretStr("dev-jwt-secret-not-for-production-00000001")
    jwt_issuer: str = "hai"
    jwt_ttl_minutes: int = 480
    cert_signing_key: SecretStr = SecretStr("dev-cert-signing-key-not-for-production-01")
    webhook_signing_key: SecretStr = SecretStr("dev-webhook-signing-key-not-for-prod-0001")

    # Storage
    blob_store_url: str = "file://./var/blobs"

    # Ontology and config
    ontology_dir: str | None = None
    connectors_config: str = "config/connectors.yaml"

    # API
    public_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    cors_origin_suffixes: list[str] = Field(default_factory=lambda: [".humaital.com", ".humanalignmentindex.com"])
    api_host: str = "0.0.0.0"  # noqa: S104 - bind address for the container
    api_port: int = 8000
    log_level: str = "INFO"
    log_json: bool = True

    # LLM
    llm_provider: str = "heuristic"
    llm_model: str = "ladder-1"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 60.0
    llm_second_opinion_provider: str | None = None
    llm_second_opinion_model: str | None = None
    prompt_version: str = "1.0.0"

    # HTTP fetching
    http_user_agent: str = "HAI-Assessment-Bot/2.0 (+https://humanalignmentindex.com)"
    http_timeout_seconds: float = 15.0
    http_total_budget_seconds: float = 120.0
    http_page_budget: int = 60
    http_min_interval_seconds: float = 0.5
    http_max_retries: int = 2

    # Worker
    worker_poll_seconds: float = 2.0
    worker_lease_seconds: int = 180
    worker_id: str = "worker-1"
    monitoring_tick_minutes: int = 60

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        return url

    @model_validator(mode="after")
    def _production_guard(self) -> Settings:
        if not self.is_production:
            return self
        problems: list[str] = []
        if self.auth_disabled:
            problems.append("HAI_AUTH_DISABLED is not allowed in production")
        for name in ("api_key_pepper", "jwt_secret", "cert_signing_key", "webhook_signing_key"):
            value: str = getattr(self, name).get_secret_value()
            if value.startswith(DEV_PREFIX):
                problems.append(f"HAI_{name.upper()} is a development secret")
            if len(value) < MIN_SECRET_LENGTH:
                problems.append(f"HAI_{name.upper()} is shorter than {MIN_SECRET_LENGTH} characters")
        if self.llm_provider != "heuristic" and self.llm_api_key is None and self.llm_provider != "ollama":
            problems.append("HAI_LLM_API_KEY is required for a remote provider")
        if problems:
            raise ValueError("unsafe production settings: " + "; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
