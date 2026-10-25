"""Incidents: canonical event keys, conservative initial status, most material criterion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from hai_core.signals import NegativeMatch
from hai_ontology.meta import CriterionDef

AUTHORITATIVE_PUBLISHER_TYPES = frozenset({"regulator_record"})
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class IncidentCandidate:
    canonical_event_key: str
    title: str
    summary: str
    severity: str
    status: str
    occurred_at: date | None
    most_material_criterion: str
    affected_pillars: tuple[str, ...]
    rule_code: str


def month_bucket(published_at: date | None) -> str:
    return published_at.strftime("%Y-%m") if published_at else "undated"


def canonical_event_key(org_id: str, rule_code: str, published_at: date | None, matched_terms: tuple[str, ...]) -> str:
    """One key per real event: organization, kind of event, month and the leading matched terms.
    Ten syndicated copies of one story in the same month share the key (AT-04)."""
    terms = ",".join(sorted({_WORD.sub("", t.lower()) for t in matched_terms})[:3])
    base = rule_code.split(":")[0]
    raw = f"{org_id}|{base}|{month_bucket(published_at)}|{terms}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def initial_status(match: NegativeMatch) -> str:
    """Only an authoritative source can substantiate automatically (IC-11)."""
    if match.initial_status == "substantiated" and match.publisher_type in AUTHORITATIVE_PUBLISHER_TYPES:
        return "substantiated"
    return "alleged"


def most_material_criterion(affected_pillars: tuple[str, ...], criteria: list[CriterionDef]) -> str:
    candidates = [c for c in criteria if c.pillar in affected_pillars] or list(criteria)
    best = candidates[0]
    for c in candidates[1:]:
        if c.materiality_weight > best.materiality_weight:
            best = c
    return best.code


def build_incident(
    org_id: str, match: NegativeMatch, published_at: date | None, criteria: list[CriterionDef], quote: str
) -> IncidentCandidate:
    key = canonical_event_key(org_id, match.rule_code, published_at, match.matched_terms)
    kind = match.rule_code.split(":")[0].replace("NEG-", "").replace("-", " ").title()
    title = f"{kind} reported ({month_bucket(published_at)})"
    summary = f"Reported in public sources: {quote[:240].strip()}"
    return IncidentCandidate(
        canonical_event_key=key,
        title=title,
        summary=summary,
        severity=match.severity,
        status=initial_status(match),
        occurred_at=published_at,
        most_material_criterion=most_material_criterion(match.affected_pillars, criteria),
        affected_pillars=match.affected_pillars,
        rule_code=match.rule_code,
    )
