"""The report resource: criteria, evidence, sources, coverage wording and execution notes.

Built from stored rows only. The browser never computes a score or a status;
it renders what this returns (AT-10). A source is listed as collected only when
a connector run succeeded for it (IC-16).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.db.store import Store
from hai_core.generated.enums import ATTRIBUTES, LABELS
from hai_core.generated.models import (
    Assessment,
    AssessmentResult,
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
    product = manifest.methodology.product

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
    pillars_out = [
        {
            "code": p.code,
            "name": p.name,
            "weight": p.weight,
            "score": float(pillars[p.code].score) if p.code in pillars else None,
            "confidence": float(pillars[p.code].confidence) if p.code in pillars else None,
            "criteria_counted": pillars[p.code].criteria_counted if p.code in pillars else 0,
            "criteria_excluded": pillars[p.code].criteria_excluded if p.code in pillars else 0,
        }
        for p in manifest.pillars
    ]
    return {
        "product": {"report_name": product.report_name, "long_name": product.long_name},
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
        "pillars": pillars_out,
        "criteria": criteria_out,
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
