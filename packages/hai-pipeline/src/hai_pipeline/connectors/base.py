"""Connector protocol and shared result types.

A connector fetches documents for one assessment and reports exactly how the
run ended. It never writes to the database; the acquisition orchestrator stores
what it returns and records the run (IC-16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from hai_core.generated.enums import ConnectorRunOutcome
from hai_pipeline.config import ConnectorConfig
from hai_pipeline.http import Budget, Fetcher


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    content: bytes
    content_type: str
    publisher_hint: str | None = None  # a publisher name when the connector knows it (RSS source)
    publisher_type_hint: str | None = None
    published_at: date | None = None
    title: str | None = None
    rights: str | None = None
    note: str | None = None  # for example "archived snapshot of <url> at <ts>"
    archived_original_url: str | None = None
    certificate_valid_until: date | None = None
    claim_text: str | None = None  # uploads enter as claims
    upload_id: str | None = None


@dataclass
class ConnectorContext:
    organization_name: str
    organization_domain: str
    website_url: str
    direct_urls: list[str]
    org_id: str
    assessment_id: str
    github_handle: str | None = None
    cik: str | None = None
    lei: str | None = None
    aliases: list[str] = field(default_factory=list)
    pending_uploads: list[dict[str, object]] = field(default_factory=list)
    api_tokens: dict[str, str] = field(default_factory=dict)


@dataclass
class ConnectorResult:
    outcome: str  # succeeded | blocked | failed | rate_limited
    documents: list[FetchedDocument] = field(default_factory=list)
    error_code: str | None = None
    notes: list[str] = field(default_factory=list)
    attempted_urls: list[str] = field(default_factory=list)

    @property
    def items_returned(self) -> int:
        return len(self.documents)


def summarise(results: list[object]) -> str:
    """Overall outcome from per-URL fetch outcomes: succeeded if anything came back,
    otherwise the dominant failure kind."""
    from hai_pipeline.http import FetchResult

    outcomes = [r.outcome for r in results if isinstance(r, FetchResult)]
    if not outcomes:
        return "succeeded"
    if any(o == "succeeded" for o in outcomes):
        return "succeeded"
    for kind in (
        ConnectorRunOutcome.BLOCKED.value,
        ConnectorRunOutcome.RATE_LIMITED.value,
        ConnectorRunOutcome.FAILED.value,
    ):
        if kind in outcomes:
            return kind
    return "failed"


class Connector(Protocol):
    code: str

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult: ...
