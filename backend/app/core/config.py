"""Application configuration.

All settings come from environment variables (see ``.env.example`` at the repo root).
Settings that would be dangerous in production are validated in ``validate_for_environment``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "RankLens"
    public_app_url: str = "http://localhost:3000"
    api_base_path: str = "/api"

    database_url: str = "postgresql+psycopg://seo:seo@localhost:5432/seo"
    redis_url: str = "redis://localhost:6379/0"

    # Secrets
    secret_key: str = Field(default="dev-insecure-secret-key-change-me", min_length=16)
    # Comma separated Fernet keys; first key encrypts, all keys decrypt (rotation).
    encryption_keys: str = ""

    # Sessions / cookies
    session_cookie_name: str = "rl_session"
    csrf_cookie_name: str = "rl_csrf"
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool = False

    # Task execution: "celery" (production) or "inline" (dev/e2e: runs jobs in a background thread)
    task_backend: Literal["celery", "inline"] = "celery"

    # Crawler limits (hard ceilings; plans may set lower values)
    crawler_user_agent: str = "RankLensBot/0.1 (+https://example.invalid/bot)"
    crawler_allowed_ports: str = "80,443"
    crawler_max_response_bytes: int = 5 * 1024 * 1024
    crawler_connect_timeout: float = 5.0
    crawler_read_timeout: float = 15.0
    crawler_total_timeout: float = 25.0
    crawler_max_redirects: int = 5
    crawler_concurrency: int = 3
    crawler_delay_seconds: float = 0.25
    crawler_hard_max_pages: int = 2000
    crawler_hard_max_depth: int = 10
    # DEV/TEST ONLY: hostnames (e.g. "127.0.0.1,localhost") allowed to resolve to private addresses.
    # Refused in production.
    ssrf_dev_allow_hosts: str = ""

    # JS rendering (Playwright). Every sub-request is routed through the SSRF-safe fetcher.
    rendering_enabled: bool = False
    chromium_executable_path: str = ""

    # AI
    ai_provider: Literal["none", "anthropic", "mock"] = "none"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    ai_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Server-side refusal fallback (Anthropic beta "server-side-fallback-2026-07-01", fallbacks="default").
    ai_refusal_fallback: bool = True
    ai_max_output_tokens: int = 16000
    ai_max_page_chars: int = 12000

    # Keyword data
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    dataforseo_base_url: str = "https://api.dataforseo.com"

    # Billing
    billing_mode: Literal["stripe", "dev"] = "dev"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
    stripe_price_agency: str = ""

    # WordPress integration
    wordpress_app_id: str = "4f3b8a3e-7d0e-4b8e-9b44-2b1f2b6d9c11"

    # Email (optional, for monitoring alerts)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # Rate limits (requests per minute)
    rate_limit_auth_per_minute: int = 10
    rate_limit_public_audit_per_hour: int = 5
    rate_limit_api_per_minute: int = 300

    # Retention
    snapshot_retention_days: int = 90
    anonymous_audit_retention_days: int = 7

    # Public quick audit
    public_audit_max_pages: int = 10

    bootstrap_admin_email: str = ""

    @field_validator("public_app_url")
    @classmethod
    def strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def allowed_ports(self) -> set[int]:
        return {int(p) for p in self.crawler_allowed_ports.split(",") if p.strip()}

    @property
    def dev_allow_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.ssrf_dev_allow_hosts.split(",") if h.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_environment(self) -> None:
        """Refuse to boot production with dev-only or insecure settings."""
        if not self.is_production:
            return
        problems = []
        if self.secret_key.startswith("dev-insecure"):
            problems.append("SECRET_KEY must be set")
        if not self.encryption_keys:
            problems.append("ENCRYPTION_KEYS must be set")
        if self.dev_allow_hosts:
            problems.append("SSRF_DEV_ALLOW_HOSTS must be empty in production")
        if self.billing_mode == "dev":
            problems.append("BILLING_MODE=dev is not allowed in production")
        if self.ai_provider == "mock":
            problems.append("AI_PROVIDER=mock is not allowed in production")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_for_environment()
    return s
