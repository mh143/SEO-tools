"""SQLAlchemy models.

Every tenant-owned table has a non-null ``org_id`` (public anonymous audits are the only
exception: their crawl runs/pages/issues have ``org_id IS NULL`` and are reachable only
through an unguessable access token). Repository helpers in ``app.services.scoping`` always
filter by ``org_id``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def org_fk(nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=nullable, index=True
    )


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x], native_enum=False, length=40)


# ---------------------------------------------------------------- enums
class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


ROLE_RANK = {Role.viewer: 0, Role.editor: 1, Role.admin: 2, Role.owner: 3}


class CrawlStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    partial = "partial"  # finished but with page failures / limits hit
    failed = "failed"
    cancelled = "cancelled"


class Severity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class FindingType(str, enum.Enum):
    error = "error"  # objectively confirmed problem
    warning = "warning"  # likely problem, context dependent
    recommendation = "recommendation"  # improvement opportunity
    info = "info"  # informational, not a problem


class IssueStatus(str, enum.Enum):
    open = "open"
    ignored = "ignored"
    fixed = "fixed"  # no longer detected in a later crawl
    regressed = "regressed"  # previously fixed/verified, detected again


class FixStatus(str, enum.Enum):
    detected = "detected"
    analyzed = "analyzed"
    drafted = "drafted"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    applying = "applying"
    verifying = "verifying"
    verified = "verified"
    rejected = "rejected"
    failed = "failed"
    externally_applied_unverified = "externally_applied_unverified"
    rolled_back = "rolled_back"


class IntegrationStatus(str, enum.Enum):
    pending = "pending"
    connected = "connected"
    error = "error"
    disconnected = "disconnected"


# ---------------------------------------------------------------- identity
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = created_col()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan_key: Mapped[str] = mapped_column(String(40), default="free", nullable=False)
    branding: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_col()

    memberships: Mapped[list[Membership]] = relationship(back_populates="org", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), nullable=False)
    created_at: Mapped[datetime] = created_col()

    org: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_col()


# ---------------------------------------------------------------- websites & integrations
class Website(Base):
    __tablename__ = "websites"
    __table_args__ = (UniqueConstraint("org_id", "hostname", name="uq_website_org_host"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    root_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    crawl_settings: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    schedule: Mapped[str] = mapped_column(String(20), default="none", nullable=False)  # none|daily|weekly|monthly
    next_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = created_col()


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(_enum(IntegrationStatus, "integration_status"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    external_site_url: Mapped[str | None] = mapped_column(String(2048))
    external_account: Mapped[str | None] = mapped_column(String(200))
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    auth_state_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    auth_state_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_col()


# ---------------------------------------------------------------- crawling
class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = org_fk(nullable=True)
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True
    )
    public_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    start_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[CrawlStatus] = mapped_column(_enum(CrawlStatus, "crawl_status"), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    pages_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_rendered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    site_data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)  # robots, sitemaps
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_col()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("crawl_run_id", "url", name="uq_page_run_url"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = org_fk(nullable=True)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2048))
    status_code: Mapped[int | None] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200))
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    redirect_chain: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    canonical: Mapped[str | None] = mapped_column(String(2048))
    h1: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    indexable: Mapped[bool | None] = mapped_column(Boolean)
    in_sitemap: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    inbound_links: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rendered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extracted: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    scores: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PageSnapshot(Base):
    __tablename__ = "page_snapshots"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = org_fk(nullable=True)
    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    html_gz: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    headers: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_col()


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (Index("ix_issue_run_rule", "crawl_run_id", "rule_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = org_fk(nullable=True)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"))
    url: Mapped[str | None] = mapped_column(String(2048))
    rule_id: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)  # technical|content|aeo|geo
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"), nullable=False)
    finding_type: Mapped[FindingType] = mapped_column(_enum(FindingType, "finding_type"), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)  # high|medium|low
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    fix_type: Mapped[str | None] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[IssueStatus] = mapped_column(_enum(IssueStatus, "issue_status"), default=IssueStatus.open, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="rule", nullable=False)  # rule|ai
    created_at: Mapped[datetime] = created_col()


# ---------------------------------------------------------------- fixes
class FixProposal(Base):
    __tablename__ = "fix_proposals"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issues.id", ondelete="SET NULL"), index=True
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True, nullable=False
    )
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    fix_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[FixStatus] = mapped_column(_enum(FixStatus, "fix_status"), nullable=False, index=True)
    generator: Mapped[str] = mapped_column(String(80), nullable=False)  # rule | ai:<model> | manual
    before: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    after: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)  # low|medium|high
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    direct_apply_supported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    apply_unsupported_reason: Mapped[str | None] = mapped_column(Text)
    verification_steps: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    validation: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    provider_resource: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    original_state: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    provider_response: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    rollback_ref: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    verification_result: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    verification_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ChangeLog(Base):
    __tablename__ = "change_logs"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    fix_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fix_proposals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_col()


# ---------------------------------------------------------------- keywords
class KeywordResearch(Base):
    __tablename__ = "keyword_research"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True, nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # measured | ai_idea | on_page
    data_provider: Mapped[str | None] = mapped_column(String(60))  # e.g. "DataForSEO (Google Ads)"
    search_volume: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[float | None] = mapped_column(Float)
    cpc: Mapped[float | None] = mapped_column(Float)
    competition: Mapped[str | None] = mapped_column(String(20))
    location: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(20))
    intent: Mapped[str | None] = mapped_column(String(40))
    related_url: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_col()


# ---------------------------------------------------------------- billing & usage
class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_org_metric_time", "org_id", "metric", "created_at"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    metric: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    ref: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_col()


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    plan_key: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), index=True)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_payment_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BillingWebhookEvent(Base):
    __tablename__ = "billing_webhook_events"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # Stripe event id
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # processing|processed|ignored|failed
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    received_at: Mapped[datetime] = created_col()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- ops
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID | None] = org_fk(nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_col()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = created_col()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
