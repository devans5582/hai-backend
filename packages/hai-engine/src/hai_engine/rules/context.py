"""Frozen inputs and mutable state for the rules.

A :class:`CriterionContext` holds only the links that name its criterion
(IC-08) and only the incidents whose most material criterion it is (IC-10). All
inputs come from the evidence snapshot; nothing here touches a database, a model
or the clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from hai_core.generated.enums import ATTRIBUTES, RANKS
from hai_ontology.meta import CriterionDef, Manifest, Methodology, PillarDef


@dataclass(frozen=True)
class FrozenLink:
    link_id: str
    span_id: str
    criterion_code: str
    polarity: str
    admissibility: str
    maturity_rung: str
    execution_level: str
    evidence_class: str
    independence: str
    source_tier: str
    publisher_type: str
    publisher_domain: str | None
    cluster_id: str | None
    document_id: str
    published_at: date | None
    certificate_valid_until: date | None
    quote: str
    canonical_url: str | None
    document_title: str | None

    @property
    def admissible(self) -> bool:
        return self.admissibility == "admissible"  # hai-codes: ok - the single admissible value

    @property
    def rung_rank(self) -> int:
        return RANKS["maturity_rung"].get(self.maturity_rung, 0)

    @property
    def tier_weight(self) -> float:
        return float(ATTRIBUTES["source_tier"][self.source_tier]["weight"])

    @property
    def rung_credit(self) -> float:
        return float(ATTRIBUTES["maturity_rung"][self.maturity_rung]["credit"])

    @property
    def class_multiplier(self) -> float:
        return float(ATTRIBUTES["evidence_class"][self.evidence_class]["multiplier"])

    @property
    def execution_bonus(self) -> float:
        return float(ATTRIBUTES["execution_level"][self.execution_level]["bonus"])

    @property
    def source_key(self) -> str:
        """Clusters count once; otherwise the publisher domain identifies a source."""
        return (
            f"cluster:{self.cluster_id}"
            if self.cluster_id
            else f"publisher:{self.publisher_domain or self.document_id}"
        )


@dataclass(frozen=True)
class FrozenIncident:
    incident_id: str
    status: str
    severity: str
    most_material_criterion: str | None
    occurred_at: date | None
    title: str | None

    @property
    def can_adjust_score(self) -> bool:
        return bool(ATTRIBUTES["incident_status"][self.status]["can_adjust_score"])

    @property
    def level_effect(self) -> str:
        return str(ATTRIBUTES["incident_severity"][self.severity]["level_effect"])

    @property
    def confidence_ceiling(self) -> float:
        return float(ATTRIBUTES["incident_severity"][self.severity]["confidence_ceiling"])


@dataclass(frozen=True)
class FrozenFinding:
    proposed_level: int
    evidence_link_ids: tuple[str, ...]
    contradicting_link_ids: tuple[str, ...]
    uncertainty: float
    model_id: str
    second_opinion_level: int | None = None
    fell_back: bool = False


@dataclass(frozen=True)
class ConnectorSummary:
    code: str
    succeeded: bool
    failed_or_blocked: bool
    items_returned: int


@dataclass(frozen=True)
class CriterionContext:
    criterion: CriterionDef
    methodology: Methodology
    links: tuple[FrozenLink, ...]
    incidents: tuple[FrozenIncident, ...]
    connector_runs: tuple[ConnectorSummary, ...]
    finding: FrozenFinding | None
    as_of: datetime
    inputs: dict[str, Any]  # applicability namespace: stage_band, size_band, direct_urls, ...
    omitted_evidence: int = 0

    @property
    def admissible_support(self) -> list[FrozenLink]:
        return [link for link in self.links if link.admissible and link.polarity == "supports"]

    @property
    def admissible_contradicting(self) -> list[FrozenLink]:
        return [link for link in self.links if link.admissible and link.polarity == "contradicts"]

    @property
    def best_rung_rank(self) -> int:
        return max((link.rung_rank for link in self.admissible_support), default=0)

    @property
    def ladder_level(self) -> int:
        """The level the evidence ladder alone supports."""
        if not self.admissible_support:
            return self.methodology.scoring.missing_level
        return self.criterion.level_for_rung(self.best_rung_rank, RANKS["maturity_rung"])

    def runs(self, codes: list[str]) -> list[ConnectorSummary]:
        return [r for r in self.connector_runs if r.code in codes]


@dataclass
class TraceEntry:
    rule_code: str
    before: dict[str, Any]
    after: dict[str, Any]
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule_code, "before": self.before, "after": self.after, "note": self.note}


@dataclass
class CriterionState:
    level: int | None = None
    coverage_state: str | None = None
    confidence: float = 0.0
    excluded: bool = False
    review_flags: list[str] = field(default_factory=list)
    caps_applied: list[str] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)
    best_rung_rank: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "coverage_state": self.coverage_state,
            "confidence": round(self.confidence, 2),
            "excluded": self.excluded,
            "review_flags": list(self.review_flags),
        }

    @property
    def counts_in_score(self) -> bool:
        return (
            not self.excluded
            and self.coverage_state is not None
            and bool(ATTRIBUTES["coverage_state"][self.coverage_state]["counts_in_score"])
        )


@dataclass(frozen=True)
class CriterionOutcome:
    criterion: CriterionDef
    state: CriterionState
    context: CriterionContext
    trace: list[TraceEntry]
    applied_rule_codes: list[str]


@dataclass(frozen=True)
class AssessmentContext:
    manifest: Manifest
    methodology: Methodology
    pillars: tuple[PillarDef, ...]
    criteria: tuple[CriterionOutcome, ...]
    stage_band: str
    size_band: str
    certification_requested: bool
    signed_certification: bool
    connector_runs: tuple[ConnectorSummary, ...]
    incidents: tuple[FrozenIncident, ...]
    as_of: datetime

    def outcome(self, code: str) -> CriterionOutcome:
        for c in self.criteria:
            if c.criterion.code == code:
                return c
        raise KeyError(code)


@dataclass
class AssessmentState:
    hai_score: float | None = None
    score_before_caps: float | None = None
    confidence_pct: float | None = None
    effectiveness: float | None = None
    pillar_scores: dict[str, tuple[float, float, int, int]] = field(
        default_factory=dict
    )  # code -> (score, conf, counted, excluded)
    outcome_status: str | None = None
    gate_reasons: list[str] = field(default_factory=list)
    review_triggers: list[str] = field(default_factory=list)
    caps_applied: list[str] = field(default_factory=list)
    certification_eligible: bool = False
    threshold_applied: float | None = None
    counted_criteria: int = 0
    excluded_criteria: int = 0
    unavailable_criteria: int = 0
    admissible_links: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "hai_score": self.hai_score,
            "confidence_pct": self.confidence_pct,
            "effectiveness": self.effectiveness,
            "outcome_status": self.outcome_status,
            "gate_reasons": list(self.gate_reasons),
            "review_triggers": list(self.review_triggers),
            "certification_eligible": self.certification_eligible,
        }
