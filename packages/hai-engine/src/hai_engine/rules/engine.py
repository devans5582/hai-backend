"""The rules engine: run criterion rules in order for every criterion, then assessment rules.

Every rule that ran is recorded with the state before and after and a note
(IC-14). The engine is deterministic: the same contexts give the same outcome.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hai_engine.rules import builtin
from hai_engine.rules.context import (
    AssessmentContext,
    AssessmentState,
    ConnectorSummary,
    CriterionContext,
    CriterionOutcome,
    CriterionState,
    FrozenIncident,
    TraceEntry,
)
from hai_engine.rules.registry import ResolvedRule, resolve
from hai_ontology.meta import Manifest


@dataclass
class EngineResult:
    criteria: list[CriterionOutcome]
    state: AssessmentState
    trace: list[TraceEntry] = field(default_factory=list)
    applied_rule_codes: list[str] = field(default_factory=list)

    def canonical(self, *, methodology_version: str, ruleset_version: str, snapshot_sha256: str) -> dict[str, Any]:
        return {
            "criteria": {
                o.criterion.code: {
                    "level": o.state.level,
                    "coverage_state": o.state.coverage_state,
                    "confidence": round(o.state.confidence, 1),
                }
                for o in self.criteria
            },
            "pillars": {
                code: {"score": v[0], "confidence": v[1]} for code, v in sorted(self.state.pillar_scores.items())
            },
            "hai_score": self.state.hai_score,
            "confidence_pct": self.state.confidence_pct,
            "effectiveness": self.state.effectiveness,
            "outcome_status": self.state.outcome_status,
            "gate_reasons": list(self.state.gate_reasons),
            "methodology_version": methodology_version,
            "ruleset_version": ruleset_version,
            "snapshot_sha256": snapshot_sha256,
        }

    def result_hash(self, *, methodology_version: str, ruleset_version: str, snapshot_sha256: str) -> str:
        payload = self.canonical(
            methodology_version=methodology_version, ruleset_version=ruleset_version, snapshot_sha256=snapshot_sha256
        )
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()


class RuleEngine:
    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self.criterion_rules, self.assessment_rules = resolve(manifest)

    @property
    def criterion_rule_codes(self) -> list[str]:
        return [r.rule.code for r in self.criterion_rules]

    def run_criterion(self, ctx: CriterionContext) -> CriterionOutcome:
        state = CriterionState()
        trace: list[TraceEntry] = []
        applied: list[str] = []
        for r in self.criterion_rules:
            before = state.snapshot()
            note = r.fn(ctx, state, dict(r.rule.parameters))
            trace.append(TraceEntry(r.rule.code, before, state.snapshot(), note))
            applied.append(r.rule.code)
        return CriterionOutcome(ctx.criterion, state, ctx, trace, applied)

    def run_assessment(
        self,
        outcomes: list[CriterionOutcome],
        *,
        stage_band: str,
        size_band: str,
        certification_requested: bool,
        signed_certification: bool,
        connector_runs: tuple[ConnectorSummary, ...],
        incidents: tuple[FrozenIncident, ...],
        as_of: Any,
    ) -> EngineResult:
        ctx = AssessmentContext(
            manifest=self.manifest,
            methodology=self.manifest.methodology,
            pillars=tuple(self.manifest.pillars),
            criteria=tuple(outcomes),
            stage_band=stage_band,
            size_band=size_band,
            certification_requested=certification_requested,
            signed_certification=signed_certification,
            connector_runs=connector_runs,
            incidents=incidents,
            as_of=as_of,
        )
        state = AssessmentState()
        trace: list[TraceEntry] = []
        before = state.snapshot()
        note = builtin.compute_scores(ctx, state)
        trace.append(TraceEntry("SCORING", before, state.snapshot(), note))
        applied: list[str] = []
        for r in self.assessment_rules:
            before = state.snapshot()
            note = r.fn(ctx, state, dict(r.rule.parameters))
            trace.append(TraceEntry(r.rule.code, before, state.snapshot(), note))
            applied.append(r.rule.code)
        return EngineResult(outcomes, state, trace, applied)

    def rules_in_order(self) -> list[ResolvedRule]:
        return [*self.criterion_rules, *self.assessment_rules]
