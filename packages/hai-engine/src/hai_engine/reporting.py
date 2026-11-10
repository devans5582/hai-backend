"""The report resource: criteria, evidence, sources, coverage wording, execution notes, evidence
basis, pillar status, evidence strength, focus-area coverage, control verification, incident response
and impact measures.

Built from stored rows only. The browser never computes a score or a status;
it renders what this returns (AT-10). A source is listed as collected only when
a connector run succeeded for it (IC-16). Counts here describe stored decisions
and frozen snapshot rows; they never change a level or a score.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.db.store import Store
from hai_core.generated.enums import ATTRIBUTES, LABELS, RANKS
from hai_core.generated.models import (
    Assessment,
    AssessmentResult,
    CertificationDecision,
    CriterionDecision,
    EvidenceSnapshot,
    Organization,
    PillarScore,
)
from hai_ontology.meta import Manifest

RUNS_SQL = """
SELECT c.code, c.name, r.outcome::text, r.items_returned, r.error_code, r.started_at, r.finished_at, r.notes
FROM hai.connector_runs r JOIN hai.connectors c ON c.id = r.connector_id
WHERE r.assessment_id = :a ORDER BY r.started_at
"""

DOCS_SQL = """
SELECT d.id, d.canonical_url, d.title, d.published_at, d.retrieved_at, d.sha256,
       p.name AS publisher, p.publisher_type::text,
       c.code AS connector, r.outcome::text AS run_outcome, d.cluster_id
FROM hai.source_documents d
JOIN hai.publishers p ON p.id = d.publisher_id
JOIN hai.connector_runs r ON r.id = d.connector_run_id
JOIN hai.connectors c ON c.id = r.connector_id
WHERE r.assessment_id = :a ORDER BY d.retrieved_at, d.canonical_url
"""


def collected_sources(conn: Connection, assessment_id: UUID) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(connector runs, documents collected through a succeeded run). IC-16."""
    runs = [dict(r) for r in conn.execute(text(RUNS_SQL), {"a": assessment_id}).mappings().all()]
    succeeded = {r["code"] for r in runs if r["outcome"] == "succeeded"}  # hai-codes: ok - connector_run_outcome value
    docs = [dict(r) for r in conn.execute(text(DOCS_SQL), {"a": assessment_id}).mappings().all()]
    collected = [d for d in docs if d["connector"] in succeeded and d["run_outcome"] == "succeeded"]  # hai-codes: ok
    return runs, collected


def coverage_wording(state: str) -> str:
    return str(ATTRIBUTES["coverage_state"][state]["report_wording"])


VERSION_SQL = """
SELECT version, versions FROM (
    SELECT id, row_number() OVER (ORDER BY created_at, id) AS version, count(*) OVER () AS versions
    FROM hai.assessments WHERE org_id = :o
) v WHERE v.id = :a
"""

BENCHMARK_SQL = """
SELECT organizations, average_score, average_confidence FROM hai_ops.v_industry_benchmarks
WHERE industry = :i AND stage_band = CAST(:s AS hai.stage_band) AND size_band = CAST(:z AS hai.size_band)
"""


def assessment_version(conn: Connection, org_id: UUID, assessment_id: UUID) -> dict[str, int]:
    """This assessment's position among the organization's assessments, oldest first (1-based)."""
    row = conn.execute(text(VERSION_SQL), {"o": org_id, "a": assessment_id}).mappings().first()
    if row is None:
        return {"number": 1, "total": 1}
    return {"number": int(row["version"]), "total": int(row["versions"])}


def industry_benchmark(
    conn: Connection, industry_code: str | None, stage_band: str, size_band: str, hai_score: float | None
) -> dict[str, Any] | None:
    """Peers with the same industry, stage and size (latest result each, access-limited excluded)."""
    if not industry_code:
        return None
    row = conn.execute(text(BENCHMARK_SQL), {"i": industry_code, "s": stage_band, "z": size_band}).mappings().first()
    if row is None or row["average_score"] is None:
        return None
    average = float(row["average_score"])
    position = None
    if hai_score is not None:
        position = "above" if hai_score > average else "below" if hai_score < average else "at"
    return {
        "industry_code": industry_code,
        "industry_label": LABELS["industry"].get(industry_code, industry_code),
        "organizations": int(row["organizations"]),
        "average_score": average,
        "average_confidence": float(row["average_confidence"]) if row["average_confidence"] is not None else None,
        "position": position,
    }


def current_certification(store: Store, assessment_id: UUID) -> CertificationDecision | None:
    rows = store.find(CertificationDecision, where={"assessment_id": assessment_id}, order_by="created_at")
    superseded = {r.supersedes_id for r in rows if r.supersedes_id}
    live = [r for r in rows if r.id not in superseded]
    return live[-1] if live else None


def _latest(rows: list[Any]) -> list[Any]:
    superseded = {r.supersedes_id for r in rows if getattr(r, "supersedes_id", None)}
    return [r for r in rows if r.id not in superseded]


def _enum_str(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def build_report(conn: Connection, store: Store, manifest: Manifest, assessment_id: UUID) -> dict[str, Any]:
    assessment = store.require(Assessment, assessment_id)
    org = store.require(Organization, assessment.org_id)
    snapshot = store.first(EvidenceSnapshot, where={"assessment_id": assessment_id})
    results = _latest(store.find(AssessmentResult, where={"assessment_id": assessment_id}, order_by="created_at"))
    result = results[-1] if results else None
    decisions = {
        _enum_str(d.criterion_code): d
        for d in _latest(store.find(CriterionDecision, where={"assessment_id": assessment_id}, order_by="created_at"))
    }
    pillars = {
        _enum_str(p.pillar_code): p
        for p in _latest(store.find(PillarScore, where={"assessment_id": assessment_id}, order_by="created_at"))
    }
    runs, documents = collected_sources(conn, assessment_id)
    link_states = snapshot.link_states if snapshot else {}
    target_states: dict[str, Any] = (
        snapshot.target_states if snapshot and isinstance(snapshot.target_states, dict) else {}
    )
    incident_states: dict[str, Any] = snapshot.incident_states if snapshot else {}
    product = manifest.methodology.product
    rung_order = [code for code, _ in sorted(RANKS["maturity_rung"].items(), key=lambda kv: kv[1])]
    overall_basis = dict.fromkeys(rung_order, 0)
    class_presence: dict[str, int] = dict.fromkeys(LABELS["evidence_class"], 0)
    counted_criteria = 0

    criteria_out: list[dict[str, Any]] = []
    execution_notes: list[dict[str, Any]] = []
    for criterion in manifest.criteria:
        d = decisions.get(criterion.code)
        links = [
            {
                "link_id": lid,
                **{
                    k: st.get(k)
                    for k in (
                        "quote",
                        "polarity",
                        "admissibility",
                        "maturity_rung",
                        "execution_level",
                        "evidence_class",
                        "independence",
                        "source_tier",
                        "publisher_name",
                        "publisher_type",
                        "published_at",
                        "canonical_url",
                        "document_title",
                        "section_heading",
                        "document_id",
                        "span_id",
                        "char_start",
                        "char_end",
                        "target_type",
                        "target_id",
                        "focus_area",
                    )
                },
            }
            for lid, st in link_states.items()
            if st.get("criterion_code") == criterion.code
        ]
        admissible_support = [
            link for link in links if link["admissibility"] == "admissible" and link["polarity"] == "supports"
        ]  # hai-codes: ok
        coverage = _enum_str(d.coverage_state) if d else None
        basis = dict.fromkeys(rung_order, 0)
        for link in admissible_support:
            rung = str(link["maturity_rung"])
            basis[rung] = basis.get(rung, 0) + 1
            overall_basis[rung] = overall_basis.get(rung, 0) + 1
        counts_in_score = bool(coverage and ATTRIBUTES["coverage_state"][coverage]["counts_in_score"])
        if counts_in_score:
            counted_criteria += 1
            for cls in {str(link["evidence_class"]) for link in admissible_support}:
                class_presence[cls] = class_presence.get(cls, 0) + 1
        trace_inputs = d.trace.get("inputs", {}) if d and isinstance(d.trace, dict) else {}
        entry = {
            "code": criterion.code,
            "name": criterion.name,
            "pillar": criterion.pillar,
            "definition": criterion.definition,
            "content_status": criterion.content_status,
            "level": d.level if d else None,
            "level_descriptor": next((lv.descriptor for lv in criterion.levels if d and lv.level == d.level), None),
            "coverage_state": coverage,
            "coverage_wording": coverage_wording(coverage) if coverage else None,
            "confidence": float(d.confidence) if d else None,
            "review_required": d.review_required if d else False,
            "applied_rule_codes": list(d.applied_rule_codes) if d else [],
            "evidence": links,
            "evidence_basis": basis,
            "best_rung": max(
                (str(link["maturity_rung"]) for link in admissible_support),
                key=lambda r: RANKS["maturity_rung"].get(r, 0),
                default=None,
            ),
            "focus_areas": list(criterion.focus_areas),
            "confidence_components": trace_inputs.get("confidence_components") or {},
            "decision_id": str(d.id) if d else None,
        }
        criteria_out.append(entry)
        if coverage in ("not_tested", "failed") or (
            admissible_support and all(link["execution_level"] in ("none", "asserted") for link in admissible_support)
        ):  # hai-codes: ok
            execution_notes.append(
                {
                    "code": criterion.code,
                    "name": criterion.name,
                    "note": "Governance documentation was found but no artefact showing the practice operated was identified in public sources. This does not mean the practice is absent; public evidence of execution was not detected.",  # noqa: E501
                }
            )
    pillars_out = []
    for p in manifest.pillars:
        stored = pillars.get(p.code)
        status = _enum_str(stored.status) if stored and stored.status else None
        pillars_out.append(
            {
                "code": p.code,
                "name": p.name,
                "weight": p.weight,
                "score": float(stored.score) if stored else None,
                "confidence": float(stored.confidence) if stored else None,
                "criteria_counted": stored.criteria_counted if stored else 0,
                "criteria_excluded": stored.criteria_excluded if stored else 0,
                "status": status,
                "status_label": LABELS["maturity_status"][status] if status else None,
                "status_wording": str(ATTRIBUTES["maturity_status"][status]["report_wording"]) if status else None,
            }
        )
    report_cfg = manifest.methodology.report
    evidence_strength = {
        cls: {
            "label": LABELS["evidence_class"][cls],
            "criteria_with_evidence": n,
            "share": round(n / counted_criteria, 3) if counted_criteria else 0.0,
            "strength": report_cfg.strength_label(n / counted_criteria) if counted_criteria else "None",
        }
        for cls, n in class_presence.items()
    }
    focus_coverage = _focus_area_coverage(manifest, link_states, rung_order)
    verification = _verification_summary(target_states, rung_order)
    incident_response = _incident_response(incident_states)
    impact_measures = _impact_measures(target_states)
    comps = manifest.methodology.confidence.components
    cert = current_certification(store, assessment_id)
    version = assessment_version(conn, assessment.org_id, assessment_id)
    benchmark = industry_benchmark(
        conn,
        org.industry_code,
        _enum_str(assessment.stage_band),
        _enum_str(assessment.size_band),
        float(result.hai_score) if result and result.hai_score is not None else None,
    )
    return {
        "product": {"report_name": product.report_name, "long_name": product.long_name},
        "scale": {
            "level_max": manifest.methodology.scoring.level_max,
            "score_scale": manifest.methodology.scoring.score_scale,
            "certification_threshold": manifest.methodology.certification.threshold,
            "min_confidence": manifest.methodology.certification.min_confidence,
        },
        "version": version,
        "assessment": {
            "id": str(assessment.id),
            "lifecycle_state": _enum_str(assessment.lifecycle_state),
            "lifecycle_label": LABELS["lifecycle_state"][_enum_str(assessment.lifecycle_state)],
            "requested_by": assessment.requested_by,
            "submitted_domain": assessment.submitted_domain,
            "stage_band": _enum_str(assessment.stage_band),
            "size_band": _enum_str(assessment.size_band),
            "versions": {
                "ontology": assessment.ontology_version,
                "methodology": assessment.methodology_version,
                "ruleset": assessment.ruleset_version,
                "prompt": assessment.prompt_version,
                "model": assessment.model_id,
            },
            "created_at": assessment.created_at.isoformat() if assessment.created_at else None,
            "finished_at": assessment.finished_at.isoformat() if assessment.finished_at else None,
        },
        "organization": {
            "id": str(org.id),
            "name": org.display_name,
            "legal_name": org.legal_name,
            "domain": org.primary_domain,
            "industry_code": org.industry_code,
        },
        "result": (
            {
                "hai_score": float(result.hai_score) if result.hai_score is not None else None,
                "confidence_pct": float(result.confidence_pct) if result.confidence_pct is not None else None,
                "effectiveness": float(result.effectiveness) if result.effectiveness is not None else None,
                "outcome_status": _enum_str(result.outcome_status),
                "outcome_label": LABELS["outcome_status"][_enum_str(result.outcome_status)],
                "gate_reasons": list(result.gate_reasons or []),
                "review_triggers": list(result.review_triggers or []),
                "caps_applied": list(result.caps_applied or []),
                "score_before_caps": float(result.score_before_caps) if result.score_before_caps is not None else None,
                "result_id": str(result.id),
                "result_sha256": result.result_sha256,
            }
            if result
            else None
        ),
        "certification": (
            {
                "decision": _enum_str(cert.decision),
                "decision_label": LABELS["certification_outcome"][_enum_str(cert.decision)],
                "certificate_number": cert.certificate_number,
                "reviewer_id": cert.reviewer_id,
                "signed_at": cert.signed_at.isoformat() if cert.signed_at else None,
                "expires_at": cert.expires_at.isoformat() if cert.expires_at else None,
                "threshold_applied": float(cert.threshold_applied),
                "gate_reasons": list(cert.gate_reasons or []),
            }
            if cert
            else None
        ),
        "benchmark": benchmark,
        "pillars": pillars_out,
        "criteria": criteria_out,
        "evidence_classes": [
            {"code": v.code, "label": v.label, "description": v.description}
            for v in manifest.vocabulary("evidence_class").values
        ],
        "status_definitions": [
            {"code": v.code, "label": v.label, "wording": str(v.attributes.get("report_wording", v.description))}
            for v in sorted(manifest.vocabulary("maturity_status").values, key=lambda v: v.rank or 0)
        ],
        "rung_definitions": [
            {"code": v.code, "label": v.label, "description": v.description}
            for v in sorted(manifest.vocabulary("maturity_rung").values, key=lambda v: v.rank or 0)
        ],
        "evidence_basis": {
            "by_rung": overall_basis,
            "labels": {code: LABELS["maturity_rung"][code] for code in rung_order},
            "criteria_counted": counted_criteria,
        },
        "evidence_strength": evidence_strength,
        "focus_areas": focus_coverage,
        "verification": verification,
        "incident_response": incident_response,
        "impact_measures": impact_measures,
        "confidence_methodology": {
            "model": manifest.methodology.confidence.model,
            "source": comps.source,
            "weights": comps.weights,
            "evidence_type_credit": dict(comps.evidence_type_credit),
        },
        "coverage_summary": {
            state: sum(1 for c in criteria_out if c["coverage_state"] == state) for state in LABELS["coverage_state"]
        },
        "connector_runs": [
            {
                **r,
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            }
            for r in runs
        ],
        "sources": [
            {
                **d,
                "id": str(d["id"]),
                "cluster_id": str(d["cluster_id"]) if d["cluster_id"] else None,
                "published_at": d["published_at"].isoformat() if d["published_at"] else None,
                "retrieved_at": d["retrieved_at"].isoformat() if d["retrieved_at"] else None,
            }
            for d in documents
        ],
        "execution_notes": execution_notes,
        "snapshot": {
            "id": str(snapshot.id),
            "frozen_at": snapshot.frozen_at.isoformat(),
            "sha256": snapshot.snapshot_sha256,
            "links": len(snapshot.link_ids),
        }
        if snapshot
        else None,
        "drafts_notice": "Criterion definitions and level descriptors marked draft are placeholders pending Humaital's canonical methodology text.",  # noqa: E501
    }


def _focus_area_coverage(
    manifest: Manifest, link_states: dict[str, Any], rung_order: list[str]
) -> list[dict[str, Any]]:
    """Per focus area: the criteria that list it, the tagged admissible supporting links and their best rung."""
    out: list[dict[str, Any]] = []
    ranks = RANKS["maturity_rung"]
    for code, label in LABELS["focus_area"].items():
        attrs = ATTRIBUTES["focus_area"][code]
        criteria = [c.code for c in manifest.criteria if code in c.focus_areas]
        tagged = [
            st
            for st in link_states.values()
            if st.get("focus_area") == code
            and st.get("admissibility") == "admissible"  # hai-codes: ok - the single admissible value
            and st.get("polarity") == "supports"
        ]
        by_rung = dict.fromkeys(rung_order, 0)
        for st in tagged:
            by_rung[str(st.get("maturity_rung"))] = by_rung.get(str(st.get("maturity_rung")), 0) + 1
        best = max((str(st.get("maturity_rung")) for st in tagged), key=lambda r: ranks.get(r, 0), default=None)
        out.append(
            {
                "code": code,
                "label": label,
                "question": str(attrs.get("question", "")),
                "cross_cutting": bool(attrs.get("cross_cutting")),
                "criteria": criteria,
                "links": len(tagged),
                "by_rung": by_rung,
                "best_rung": best,
                "best_rung_label": LABELS["maturity_rung"][best] if best else None,
            }
        )
    return out


def _verification_summary(target_states: dict[str, Any], rung_order: list[str]) -> dict[str, Any]:
    """Controls with claimed capabilities, whether a passing test exercised them, and tests by method and threat."""
    del rung_order
    controls = target_states.get("controls") or {}
    tests = target_states.get("test_outcomes") or []
    exercised_by_control: dict[str, set[str]] = {}
    for t in tests:
        method = t.get("method")
        exercises = method is None or bool(ATTRIBUTES["verification_method"][str(method)]["exercises_control"])
        if t.get("result") == "pass" and exercises:  # hai-codes: ok - test_result value
            exercised_by_control.setdefault(str(t.get("control_id")), set()).update(
                str(x) for x in t.get("capabilities_exercised") or []
            )
    controls_out = []
    for cid, c in controls.items():
        claimed = [str(x) for x in c.get("capabilities") or []]
        if not claimed and c.get("can_pause_or_rollback"):
            claimed = ["pause", "rollback"]  # hai-codes: ok - control_capability values
        exercised = sorted(set(claimed) & exercised_by_control.get(cid, set()))
        controls_out.append(
            {
                "control_id": cid,
                "name": c.get("name"),
                "claimed_capabilities": claimed,
                "exercised_capabilities": exercised,
                "unexercised_capabilities": sorted(set(claimed) - set(exercised)),
                "monitoring_mode": c.get("monitoring_mode"),
                "operational_status": c.get("operational_status"),
                "tests": sum(1 for t in tests if str(t.get("control_id")) == cid),
            }
        )
    by_method: dict[str, int] = {}
    threats: dict[str, int] = {}
    for t in tests:
        by_method[str(t.get("method") or "unspecified")] = by_method.get(str(t.get("method") or "unspecified"), 0) + 1
        for th in t.get("threats_exercised") or []:
            threats[str(th)] = threats.get(str(th), 0) + 1
    systems = [
        {
            "system_id": sid,
            **{k: v for k, v in sv.items() if k in ("name", "autonomy_level", "monitoring_mode", "criticality")},
        }
        for sid, sv in (target_states.get("ai_systems") or {}).items()
    ]
    return {
        "controls": controls_out,
        "tests_by_method": by_method,
        "threats_exercised": threats,
        "ai_systems": systems,
        "controls_with_unexercised_capabilities": sum(1 for c in controls_out if c["unexercised_capabilities"]),
    }


def _incident_response(incident_states: dict[str, Any]) -> list[dict[str, Any]]:
    """Response timeline per incident: days to disclose, contain and correct, and whether the fix was verified."""

    def days(a: str | None, b: str | None) -> int | None:
        if not a or not b:
            return None
        from datetime import date

        return (date.fromisoformat(b) - date.fromisoformat(a)).days

    out = []
    for incident_id, st in incident_states.items():
        start = st.get("detected_at") or st.get("occurred_at")
        out.append(
            {
                "incident_id": incident_id,
                "title": st.get("title"),
                "status": st.get("status"),
                "severity": st.get("severity"),
                "containment_threat": st.get("containment_threat"),
                "occurred_at": st.get("occurred_at"),
                "detected_at": st.get("detected_at"),
                "disclosed_at": st.get("disclosed_at"),
                "contained_at": st.get("contained_at"),
                "corrected_at": st.get("corrected_at"),
                "correction_verified_at": st.get("correction_verified_at"),
                "days_to_disclose": days(start, st.get("disclosed_at")),
                "days_to_contain": days(start, st.get("contained_at")),
                "days_to_correct": days(start, st.get("corrected_at")),
                "correction_verified": bool(st.get("correction_verified_at") and st.get("correction_verified_by")),
            }
        )
    return out


def _impact_measures(target_states: dict[str, Any]) -> dict[str, Any]:
    """Impact measures by kind: stated intention and output counts versus measured and evaluated outcomes."""
    measures = target_states.get("impact_measures") or []
    by_kind = dict.fromkeys(LABELS["impact_evidence_kind"], 0)
    for m in measures:
        by_kind[str(m.get("kind"))] = by_kind.get(str(m.get("kind")), 0) + 1
    demonstrated = sum(
        1 for m in measures if ATTRIBUTES["impact_evidence_kind"][str(m.get("kind"))]["demonstrates_benefit"]
    )
    return {
        "items": [
            {
                "id": m.get("id"),
                "kind": m.get("kind"),
                "kind_label": LABELS["impact_evidence_kind"][str(m.get("kind"))],
                "outcome": m.get("outcome"),
                "measured_at": m.get("measured_at"),
                "period_months": m.get("period_months"),
                "verified_independently": bool(m.get("verifier_org_id")),
                "demonstrates_benefit": bool(
                    ATTRIBUTES["impact_evidence_kind"][str(m.get("kind"))]["demonstrates_benefit"]
                ),
            }
            for m in measures
        ],
        "by_kind": by_kind,
        "demonstrated_benefit": demonstrated,
        "total": len(measures),
    }
