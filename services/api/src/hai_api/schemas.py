"""Request and response models. Response shapes are consistent across endpoints:
single resources are plain objects, lists are ``{"items", "total", "limit", "offset"}``,
errors are ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_name: str = Field(min_length=1, max_length=200)
    website: str = Field(
        min_length=3, max_length=500, description="Domain or URL of the organization's official website"
    )
    stage: str = Field(description="Stage band or a Phase 6 alias such as startup")
    size: str = Field(description="Size band or a Phase 6 alias such as 11-50")
    industry: str | None = Field(default=None, max_length=120)
    direct_urls: list[str] = Field(default_factory=list, max_length=10)
    certification_requested: bool = False
    legal_name: str | None = None
    aliases: list[str] = Field(default_factory=list, max_length=10)


class AssessmentOut(BaseModel):
    id: UUID
    org_id: UUID
    parent_assessment_id: UUID | None
    requested_by: str
    submitted_domain: str
    direct_urls: list[str]
    stage_band: str
    size_band: str
    lifecycle_state: str
    lifecycle_label: str
    certification_requested: bool
    failure_reason: str | None
    versions: dict[str, str]
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    links: dict[str, str]


class ResultOut(BaseModel):
    assessment_id: UUID
    result_id: UUID
    hai_score: float | None
    confidence_pct: float | None
    effectiveness: float | None
    outcome_status: str
    outcome_label: str
    gate_reasons: list[str]
    review_triggers: list[str]
    caps_applied: list[str]
    score_before_caps: float | None
    pillars: list[dict[str, Any]]
    ruleset_version: str
    result_sha256: str
    created_at: datetime | None


class DecisionOut(BaseModel):
    id: UUID
    criterion_code: str
    criterion_name: str
    pillar: str
    level: int | None
    coverage_state: str
    coverage_wording: str
    confidence: float
    applied_rule_codes: list[str]
    review_required: bool
    finding_id: UUID | None
    created_at: datetime | None


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    action: str
    reason: str = Field(min_length=3, max_length=2000)


class CertificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(description="certified or not_certified")
    reason: str = Field(min_length=3, max_length=2000)


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="reviewer", pattern="^(reviewer|admin)$")
    scopes: list[str] | None = None
    ttl_minutes: int | None = Field(default=None, ge=5, le=60 * 24 * 30)


class TokenOut(BaseModel):
    token: str
    token_type: str = "bearer"  # noqa: S105 - not a secret
    role: str
    scopes: list[str]
    expires_in_minutes: int


class WebhookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=1000)
    events: list[str] = Field(min_length=1)
    secret: str = Field(min_length=16, max_length=200)


class MonitoringCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_days: int = Field(default=90, ge=1, le=365)


class OrganizationOut(BaseModel):
    id: UUID
    legal_name: str
    display_name: str
    primary_domain: str
    aliases: list[str]
    industry_code: str | None
    stage_band: str | None
    size_band: str | None
    identifiers: dict[str, str | None]
    identifiers_verified: bool
    entity_confidence: float | None
    created_at: datetime | None


class ReassessOut(BaseModel):
    assessment: AssessmentOut
    parent_assessment_id: UUID
