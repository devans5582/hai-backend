"""Decision service: decide, finalize and a read-only replay.

``decide`` reads only the frozen snapshot and the accepted findings, runs the
rules engine and writes criterion decisions, pillar scores and the result.
``finalize`` runs again after reviews with the review overlay (admissibility and
incident status changes made by reviewers on rows in the snapshot) and writes
superseding rows. ``replay`` recomputes from the snapshot and the overlay
recorded in the decisions and must match the stored result hash (AT-07).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.db.store import Store
from hai_core.generated.enums import Admissibility, CoverageState, OutcomeStatus, PillarCode
from hai_core.generated.models import (
    Assessment,
    AssessmentResult,
    CriterionDecision,
    CriterionFinding,
    EvidenceSnapshot,
    PillarScore,
)
from hai_engine.packs import build_all_packs
from hai_engine.rules.context import ConnectorSummary, CriterionContext, FrozenFinding, FrozenIncident, FrozenLink
from hai_engine.rules.engine import EngineResult, RuleEngine
from hai_ontology.meta import Manifest


@dataclass
class ReviewOverlay:
    """Changes reviewers made to rows that are in the snapshot."""

    link_admissibility: dict[str, str] = field(default_factory=dict)
    incident_status: dict[str, str] = field(default_factory=dict)
    resolved_contradictions: list[str] = field(default_factory=list)  # criterion codes approved by review
    rejected_support: list[str] = field(default_factory=list)  # criterion codes whose support was rejected

    def as_dict(self) -> dict[str, Any]:
        return {
            "link_admissibility": dict(sorted(self.link_admissibility.items())),
            "incident_status": dict(sorted(self.incident_status.items())),
            "resolved_contradictions": sorted(self.resolved_contradictions),
            "rejected_support": sorted(self.rejected_support),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ReviewOverlay:
        data = data or {}
        return cls(
            link_admissibility=dict(data.get("link_admissibility", {})),
            incident_status=dict(data.get("incident_status", {})),
            resolved_contradictions=list(data.get("resolved_contradictions", [])),
            rejected_support=list(data.get("rejected_support", [])),
        )

    @property
    def empty(self) -> bool:
        return not (
            self.link_admissibility or self.incident_status or self.resolved_contradictions or self.rejected_support
        )


@dataclass
class Decision:
    assessment_id: UUID
    result: AssessmentResult
    decisions: list[CriterionDecision]
    pillar_scores: list[PillarScore]
    engine: EngineResult
    review_triggers: list[str]


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def frozen_links(snapshot: EvidenceSnapshot, overlay: ReviewOverlay) -> list[FrozenLink]:
    out: list[FrozenLink] = []
    for link_id, st in snapshot.link_states.items():
        admissibility = overlay.link_admissibility.get(link_id, st["admissibility"])
        if st["criterion_code"] in overlay.rejected_support and st["polarity"] == "supports":
            admissibility = Admissibility.PENDING_REVIEW.value
        out.append(
            FrozenLink(
                link_id=link_id,
                span_id=str(st["span_id"]),
                criterion_code=str(st["criterion_code"]),
                polarity=str(st["polarity"]),
                admissibility=str(admissibility),
                maturity_rung=str(st["maturity_rung"]),
                execution_level=str(st["execution_level"]),
                evidence_class=str(st["evidence_class"]),
                independence=str(st["independence"]),
                source_tier=str(st["source_tier"]),
                publisher_type=str(st["publisher_type"]),
                publisher_domain=st.get("publisher_domain"),
                cluster_id=st.get("cluster_id"),
                document_id=str(st["document_id"]),
                published_at=_date(st.get("published_at")),
                certificate_valid_until=_date(st.get("certificate_valid_until")),
                quote=str(st["quote"]),
                canonical_url=st.get("canonical_url"),
                document_title=st.get("document_title"),
            )
        )
    return out


def frozen_incidents(snapshot: EvidenceSnapshot, overlay: ReviewOverlay) -> list[FrozenIncident]:
    return [
        FrozenIncident(
            incident_id=incident_id,
            status=overlay.incident_status.get(incident_id, str(st["status"])),
            severity=str(st["severity"]),
            most_material_criterion=st.get("most_material_criterion"),
            occurred_at=_date(st.get("occurred_at")),
            title=st.get("title"),
        )
        for incident_id, st in snapshot.incident_states.items()
    ]


def connector_summaries(snapshot: EvidenceSnapshot) -> tuple[ConnectorSummary, ...]:
    return tuple(
        ConnectorSummary(
            code, bool(v.get("succeeded")), bool(v.get("failed_or_blocked")), int(v.get("items_returned", 0))
        )
        for code, v in sorted(snapshot.connector_runs.items())
    )


def build_contexts(
    manifest: Manifest,
    assessment: Assessment,
    snapshot: EvidenceSnapshot,
    findings: dict[str, FrozenFinding],
    overlay: ReviewOverlay,
    *,
    omitted: dict[str, int] | None = None,
) -> list[CriterionContext]:
    links = frozen_links(snapshot, overlay)
    incidents = frozen_incidents(snapshot, overlay)
    runs = connector_summaries(snapshot)
    inputs = {
        "stage_band": assessment.stage_band.value
        if hasattr(assessment.stage_band, "value")
        else str(assessment.stage_band),
        "size_band": assessment.size_band.value
        if hasattr(assessment.size_band, "value")
        else str(assessment.size_band),
        "direct_urls": len(assessment.direct_urls or []),
        "certification_requested": assessment.certification_requested,
    }
    out: list[CriterionContext] = []
    for criterion in manifest.criteria:
        c_links = tuple(link for link in links if link.criterion_code == criterion.code)
        c_incidents = tuple(i for i in incidents if i.most_material_criterion == criterion.code)
        finding = findings.get(criterion.code)
        if criterion.code in overlay.resolved_contradictions:
            # a reviewer approved the supporting side: contradicting links no longer block
            c_links = tuple(
                FrozenLink(**{**link.__dict__, "admissibility": Admissibility.PENDING_REVIEW.value})
                if link.polarity == "contradicts"
                else link
                for link in c_links
            )  # hai-codes: ok
        out.append(
            CriterionContext(
                criterion=criterion,
                methodology=manifest.methodology,
                links=c_links,
                incidents=c_incidents,
                connector_runs=runs,
                finding=finding,
                as_of=snapshot.frozen_at,
                inputs=inputs,
                omitted_evidence=(omitted or {}).get(criterion.code, 0),
            )
        )
    return out


def run_engine(
    manifest: Manifest,
    assessment: Assessment,
    snapshot: EvidenceSnapshot,
    findings: dict[str, FrozenFinding],
    overlay: ReviewOverlay,
    *,
    signed_certification: bool,
    omitted: dict[str, int] | None = None,
) -> EngineResult:
    engine = RuleEngine(manifest)
    contexts = build_contexts(manifest, assessment, snapshot, findings, overlay, omitted=omitted)
    outcomes = [engine.run_criterion(ctx) for ctx in contexts]
    return engine.run_assessment(
        outcomes,
        stage_band=str(contexts[0].inputs["stage_band"]) if contexts else "",
        size_band=str(contexts[0].inputs["size_band"]) if contexts else "",
        certification_requested=assessment.certification_requested,
        signed_certification=signed_certification,
        connector_runs=connector_summaries(snapshot),
        incidents=tuple(frozen_incidents(snapshot, overlay)),
        as_of=snapshot.frozen_at,
    )


class DecisionService:
    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest

    # ------------------------------------------------------------- read inputs
    def accepted_findings(self, store: Store, assessment_id: UUID) -> tuple[dict[str, FrozenFinding], dict[str, UUID]]:
        rows = store.find(
            CriterionFinding,
            where={"assessment_id": assessment_id, "validation_status": "accepted"},
            order_by="created_at",
        )  # hai-codes: ok
        primary: dict[str, CriterionFinding] = {}
        second: dict[str, CriterionFinding] = {}
        for f in rows:
            code = str(f.criterion_code.value if hasattr(f.criterion_code, "value") else f.criterion_code)
            if f.role == "second_opinion":
                second[code] = f
            else:
                primary[code] = f  # the latest accepted primary wins
        findings: dict[str, FrozenFinding] = {}
        ids: dict[str, UUID] = {}
        for code, f in primary.items():
            so = second.get(code)
            findings[code] = FrozenFinding(
                proposed_level=f.proposed_level,
                evidence_link_ids=tuple(str(x) for x in f.evidence_link_ids),
                contradicting_link_ids=tuple(str(x) for x in (f.contradicting_link_ids or [])),
                uncertainty=float(f.uncertainty),
                model_id=f.model_id,
                second_opinion_level=so.proposed_level if so else None,
                fell_back=bool((f.raw_output or {}).get("fell_back")) if isinstance(f.raw_output, dict) else False,
            )
            ids[code] = f.id
        return findings, ids

    def overlay_from_reviews(self, conn: Connection, snapshot: EvidenceSnapshot) -> ReviewOverlay:
        """Reviewer changes to rows in the snapshot: live link admissibility and incident status
        that differ from the frozen copy, and contradiction decisions."""
        overlay = ReviewOverlay()
        link_ids = [UUID(k) for k in snapshot.link_states]
        if link_ids:
            rows = conn.execute(
                text(
                    "SELECT id, admissibility::text FROM hai.evidence_links WHERE id = ANY(:ids) AND reviewer_id IS NOT NULL"  # noqa: E501
                ),
                {"ids": link_ids},
            ).all()
            for link_id, adm in rows:
                if snapshot.link_states[str(link_id)]["admissibility"] != adm:
                    overlay.link_admissibility[str(link_id)] = str(adm)
        incident_ids = [UUID(k) for k in snapshot.incident_states]
        if incident_ids:
            rows = conn.execute(
                text("SELECT id, status::text FROM hai.incidents WHERE id = ANY(:ids)"), {"ids": incident_ids}
            ).all()
            for incident_id, status in rows:
                if snapshot.incident_states[str(incident_id)]["status"] != status:
                    overlay.incident_status[str(incident_id)] = str(status)
        rows = conn.execute(
            text(
                "SELECT r.action::text, d.criterion_code::text FROM hai.reviews r "
                "JOIN hai.criterion_decisions d ON d.id = r.subject_id "
                "WHERE r.assessment_id = :a AND r.subject_type = 'contradiction' ORDER BY r.decided_at"
            ),
            {"a": snapshot.assessment_id},
        ).all()
        for action, code in rows:
            if action == "approve":
                overlay.resolved_contradictions.append(str(code))
                overlay.rejected_support = [c for c in overlay.rejected_support if c != code]
            elif action == "reject":
                overlay.rejected_support.append(str(code))
                overlay.resolved_contradictions = [c for c in overlay.resolved_contradictions if c != code]
        return overlay

    def signed_certification_exists(self, conn: Connection, assessment_id: UUID) -> bool:
        row = conn.execute(
            text(
                "SELECT 1 FROM hai.certification_decisions cd WHERE cd.assessment_id = :a AND cd.decision = 'certified' "  # noqa: E501
                "AND NOT EXISTS (SELECT 1 FROM hai.certification_decisions later WHERE later.supersedes_id = cd.id) LIMIT 1"  # noqa: E501
            ),
            {"a": assessment_id},
        ).first()
        return row is not None

    def omitted_counts(self, snapshot: EvidenceSnapshot) -> dict[str, int]:
        packs = build_all_packs(list(self.manifest.criteria), snapshot.link_states)
        return {code: pack.omitted for code, pack in packs.items()}

    # ------------------------------------------------------------------ writes
    def decide(
        self,
        conn: Connection,
        store: Store,
        assessment_id: UUID,
        *,
        overlay: ReviewOverlay | None = None,
        reason: str = "decide",
    ) -> Decision:
        assessment = store.require(Assessment, assessment_id)
        snapshot = store.first(EvidenceSnapshot, where={"assessment_id": assessment_id})
        if snapshot is None:
            raise ValueError("no evidence snapshot; freeze before deciding")
        findings, finding_ids = self.accepted_findings(store, assessment_id)
        overlay = overlay if overlay is not None else ReviewOverlay()
        signed = self.signed_certification_exists(conn, assessment_id)
        omitted = self.omitted_counts(snapshot)
        engine_result = run_engine(
            self.manifest, assessment, snapshot, findings, overlay, signed_certification=signed, omitted=omitted
        )
        return self._persist(store, assessment, snapshot, engine_result, finding_ids, overlay, reason=reason)

    def finalize(self, conn: Connection, store: Store, assessment_id: UUID) -> Decision:
        snapshot = store.first(EvidenceSnapshot, where={"assessment_id": assessment_id})
        if snapshot is None:
            raise ValueError("no evidence snapshot")
        overlay = self.overlay_from_reviews(conn, snapshot)
        return self.decide(conn, store, assessment_id, overlay=overlay, reason="finalize after review")

    def _persist(
        self,
        store: Store,
        assessment: Assessment,
        snapshot: EvidenceSnapshot,
        engine_result: EngineResult,
        finding_ids: dict[str, UUID],
        overlay: ReviewOverlay,
        *,
        reason: str,
    ) -> Decision:
        previous_decisions = {
            str(d.criterion_code.value if hasattr(d.criterion_code, "value") else d.criterion_code): d
            for d in self._latest_decisions(store, assessment.id)
        }
        decisions: list[CriterionDecision] = []
        for outcome in engine_result.criteria:
            code = outcome.criterion.code
            trace = {
                "rules": [t.as_dict() for t in outcome.trace],
                "inputs": {
                    "overlay": overlay.as_dict(),
                    "admissible_support": [link.link_id for link in outcome.context.admissible_support],
                    "admissible_contradicting": [link.link_id for link in outcome.context.admissible_contradicting],
                    "incidents": [i.incident_id for i in outcome.context.incidents],
                    "omitted_evidence": outcome.context.omitted_evidence,
                },
                "caps_applied": list(outcome.state.caps_applied),
                "adjustments": list(outcome.state.adjustments),
            }
            row = CriterionDecision(
                assessment_id=assessment.id,
                criterion_code=code,
                level=outcome.state.level,
                coverage_state=CoverageState(outcome.state.coverage_state or CoverageState.MISSING.value),
                confidence=round(outcome.state.confidence, 1),
                applied_rule_codes=list(outcome.applied_rule_codes),
                finding_id=finding_ids.get(code),
                trace=trace,
                review_required=bool(outcome.state.review_flags),
            )
            prev = previous_decisions.get(code)
            decisions.append(store.supersede(prev, row, reason=reason) if prev else store.insert(row, reason=reason))
        previous_pillars = {
            str(p.pillar_code.value if hasattr(p.pillar_code, "value") else p.pillar_code): p
            for p in self._latest_pillars(store, assessment.id)
        }
        pillar_rows: list[PillarScore] = []
        for code, (score, confidence, counted, excluded) in engine_result.state.pillar_scores.items():
            row_p = PillarScore(
                assessment_id=assessment.id,
                pillar_code=PillarCode(code),
                score=score,
                confidence=confidence,
                criteria_counted=counted,
                criteria_excluded=excluded,
            )
            prev_p = previous_pillars.get(code)
            pillar_rows.append(
                store.supersede(prev_p, row_p, reason=reason) if prev_p else store.insert(row_p, reason=reason)
            )
        st = engine_result.state
        result_hash = engine_result.result_hash(
            methodology_version=assessment.methodology_version,
            ruleset_version=assessment.ruleset_version,
            snapshot_sha256=snapshot.snapshot_sha256,
        )
        result = AssessmentResult(
            assessment_id=assessment.id,
            hai_score=st.hai_score,
            confidence_pct=st.confidence_pct,
            effectiveness=st.effectiveness,
            score_before_caps=st.score_before_caps,
            caps_applied=list(st.caps_applied),
            outcome_status=OutcomeStatus(st.outcome_status or OutcomeStatus.INSUFFICIENT_EVIDENCE.value),
            gate_reasons=list(st.gate_reasons),
            review_triggers=list(st.review_triggers),
            ruleset_version=assessment.ruleset_version,
            result_sha256=result_hash,
        )
        prev_result = self.latest_result(store, assessment.id)
        stored = (
            store.supersede(prev_result, result, reason=reason) if prev_result else store.insert(result, reason=reason)
        )
        return Decision(assessment.id, stored, decisions, pillar_rows, engine_result, list(st.review_triggers))

    # ------------------------------------------------------------------- reads
    def _latest_decisions(self, store: Store, assessment_id: UUID) -> list[CriterionDecision]:
        rows = store.find(CriterionDecision, where={"assessment_id": assessment_id}, order_by="created_at")
        superseded = {r.supersedes_id for r in rows if r.supersedes_id}
        return [r for r in rows if r.id not in superseded]

    def _latest_pillars(self, store: Store, assessment_id: UUID) -> list[PillarScore]:
        rows = store.find(PillarScore, where={"assessment_id": assessment_id}, order_by="created_at")
        superseded = {r.supersedes_id for r in rows if r.supersedes_id}
        return [r for r in rows if r.id not in superseded]

    def latest_decisions(self, store: Store, assessment_id: UUID) -> list[CriterionDecision]:
        return self._latest_decisions(store, assessment_id)

    def latest_pillars(self, store: Store, assessment_id: UUID) -> list[PillarScore]:
        return self._latest_pillars(store, assessment_id)

    def latest_result(self, store: Store, assessment_id: UUID) -> AssessmentResult | None:
        rows = store.find(AssessmentResult, where={"assessment_id": assessment_id}, order_by="created_at")
        superseded = {r.supersedes_id for r in rows if r.supersedes_id}
        live = [r for r in rows if r.id not in superseded]
        return live[-1] if live else None

    # ------------------------------------------------------------------ replay
    def replay(self, conn: Connection, store: Store, assessment_id: UUID) -> tuple[bool, str, str]:
        """Recompute from the frozen snapshot and the overlay recorded in the decisions. Writes nothing."""
        assessment = store.require(Assessment, assessment_id)
        snapshot = store.first(EvidenceSnapshot, where={"assessment_id": assessment_id})
        stored = self.latest_result(store, assessment_id)
        if snapshot is None or stored is None:
            raise ValueError("nothing to replay")
        decisions = self._latest_decisions(store, assessment_id)
        overlay = ReviewOverlay.from_dict(
            (decisions[0].trace or {}).get("inputs", {}).get("overlay")
            if decisions and isinstance(decisions[0].trace, dict)
            else None
        )
        findings, _ = self.accepted_findings(store, assessment_id)
        signed = stored.outcome_status == OutcomeStatus.HAI_CERTIFIED or self.signed_certification_exists(
            conn, assessment_id
        )
        result = run_engine(
            self.manifest,
            assessment,
            snapshot,
            findings,
            overlay,
            signed_certification=signed,
            omitted=self.omitted_counts(snapshot),
        )
        recomputed = result.result_hash(
            methodology_version=assessment.methodology_version,
            ruleset_version=assessment.ruleset_version,
            snapshot_sha256=snapshot.snapshot_sha256,
        )
        return recomputed == stored.result_sha256, recomputed, stored.result_sha256


def certification_signed(conn: Connection, assessment_id: UUID) -> bool:
    return DecisionService.signed_certification_exists(DecisionService.__new__(DecisionService), conn, assessment_id)
