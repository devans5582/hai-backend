"""Snapshot freeze: copy every link's judgment columns, incident states and response timelines,
the organization's controls, test outcomes, AI systems and impact measures, connector-run outcomes
and version pins into an EvidenceSnapshot. The rules engine reads only this (AT-07)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from hai_core.db.store import Store
from hai_core.generated.enums import ConnectorRunOutcome
from hai_core.generated.models import Assessment, EvidenceSnapshot
from hai_ontology.meta import Manifest

UNAVAILABLE_OUTCOMES = (
    ConnectorRunOutcome.FAILED.value,
    ConnectorRunOutcome.BLOCKED.value,
    ConnectorRunOutcome.RATE_LIMITED.value,
)


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


LINK_QUERY = """
SELECT l.id AS link_id, l.span_id, l.target_type::text, l.target_id, l.criterion_code::text, l.polarity::text,
       l.admissibility::text, l.admissibility_reason, l.maturity_rung::text, l.execution_level::text,
       l.evidence_class::text, l.independence::text, l.source_tier::text, l.focus_area::text, l.relevance, l.proposer,
       s.quote, s.char_start, s.char_end, s.section_heading,
       d.id AS document_id, d.cluster_id, d.canonical_url, d.published_at, d.title AS document_title,
       d.valid_to AS certificate_valid_until, d.text_sha256,
       p.publisher_type::text, p.name AS publisher_name, p.domain AS publisher_domain,
       r.id AS run_id, r.outcome::text AS run_outcome, c.code AS connector_code
FROM hai.evidence_links l
JOIN hai.evidence_spans s ON s.id = l.span_id
JOIN hai.source_documents d ON d.id = s.source_document_id
JOIN hai.publishers p ON p.id = d.publisher_id
JOIN hai.connector_runs r ON r.id = d.connector_run_id
JOIN hai.connectors c ON c.id = r.connector_id
WHERE r.assessment_id = :assessment_id
  AND NOT EXISTS (SELECT 1 FROM hai.evidence_links newer WHERE newer.supersedes_id = l.id)
ORDER BY l.created_at, l.id
"""

INCIDENT_QUERY = """
SELECT id, canonical_event_key, status::text, severity::text, most_material_criterion::text, occurred_at, title,
       containment_threat::text, detected_at, disclosed_at, contained_at, corrected_at, correction_verified_at,
       correction_verified_by_org_id
FROM hai.incidents WHERE org_id = :org_id ORDER BY created_at
"""

CONTROLS_QUERY = """
SELECT id, name, ai_system_id, capabilities, monitoring_mode::text, operational_status::text, can_pause_or_rollback
FROM hai.controls WHERE org_id = :org_id ORDER BY created_at
"""

TESTS_QUERY = """
SELECT t.id, t.control_id, t.result::text, t.method::text, t.capabilities_exercised, t.threats_exercised,
       t.performed_at, t.verifier_org_id
FROM hai.test_outcomes t JOIN hai.controls c ON c.id = t.control_id
WHERE c.org_id = :org_id ORDER BY t.performed_at, t.created_at
"""

SYSTEMS_QUERY = """
SELECT id, name, autonomy_level::text, monitoring_mode::text, criticality::text
FROM hai.ai_systems WHERE owner_org_id = :org_id ORDER BY created_at
"""

IMPACT_QUERY = """
SELECT id, kind::text, outcome, verifier_org_id, measured_at, period_months, ai_system_id
FROM hai.impact_measures WHERE org_id = :org_id ORDER BY created_at
"""

RUNS_QUERY = """
SELECT c.code, r.outcome::text, r.items_returned, r.error_code, r.started_at, r.finished_at
FROM hai.connector_runs r JOIN hai.connectors c ON c.id = r.connector_id
WHERE r.assessment_id = :assessment_id ORDER BY r.started_at
"""


def build_snapshot(
    conn: Connection, store: Store, assessment: Assessment, manifest: Manifest, *, frozen_at: datetime | None = None
) -> EvidenceSnapshot:
    when = frozen_at or datetime.now(UTC)
    link_rows = conn.execute(text(LINK_QUERY), {"assessment_id": assessment.id}).mappings().all()
    link_states: dict[str, dict[str, Any]] = {}
    span_ids: list[UUID] = []
    link_ids: list[UUID] = []
    for r in link_rows:
        link_ids.append(r["link_id"])
        if r["span_id"] not in span_ids:
            span_ids.append(r["span_id"])
        link_states[str(r["link_id"])] = {
            "span_id": str(r["span_id"]),
            "target_type": r["target_type"],
            "target_id": str(r["target_id"]),
            "criterion_code": r["criterion_code"],
            "polarity": r["polarity"],
            "admissibility": r["admissibility"],
            "admissibility_reason": r["admissibility_reason"],
            "maturity_rung": r["maturity_rung"],
            "execution_level": r["execution_level"],
            "evidence_class": r["evidence_class"],
            "independence": r["independence"],
            "source_tier": r["source_tier"],
            "focus_area": r["focus_area"],
            "relevance": float(r["relevance"]) if r["relevance"] is not None else None,
            "proposer": r["proposer"],
            "quote": r["quote"],
            "char_start": int(r["char_start"]),
            "char_end": int(r["char_end"]),
            "section_heading": r["section_heading"],
            "quote_sha256": hashlib.sha256(str(r["quote"]).encode("utf-8")).hexdigest(),
            "document_id": str(r["document_id"]),
            "cluster_id": str(r["cluster_id"]) if r["cluster_id"] else None,
            "canonical_url": r["canonical_url"],
            "document_title": r["document_title"],
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
            "certificate_valid_until": r["certificate_valid_until"].isoformat()
            if r["certificate_valid_until"]
            else None,
            "text_sha256": r["text_sha256"],
            "publisher_type": r["publisher_type"],
            "publisher_name": r["publisher_name"],
            "publisher_domain": r["publisher_domain"],
            "connector_code": r["connector_code"],
            "run_outcome": r["run_outcome"],
        }
    incident_rows = conn.execute(text(INCIDENT_QUERY), {"org_id": assessment.org_id}).mappings().all()
    incident_states = {
        str(r["id"]): {
            "canonical_event_key": r["canonical_event_key"],
            "status": r["status"],
            "severity": r["severity"],
            "most_material_criterion": r["most_material_criterion"],
            "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
            "title": r["title"],
            "containment_threat": r["containment_threat"],
            "detected_at": _iso(r["detected_at"]),
            "disclosed_at": _iso(r["disclosed_at"]),
            "contained_at": _iso(r["contained_at"]),
            "corrected_at": _iso(r["corrected_at"]),
            "correction_verified_at": _iso(r["correction_verified_at"]),
            "correction_verified_by": str(r["correction_verified_by_org_id"])
            if r["correction_verified_by_org_id"]
            else None,
        }
        for r in incident_rows
    }
    target_states = _target_states(conn, assessment.org_id)
    run_rows = conn.execute(text(RUNS_QUERY), {"assessment_id": assessment.id}).mappings().all()
    connector_runs: dict[str, dict[str, Any]] = {}
    for r in run_rows:
        code = str(r["code"])
        entry = connector_runs.setdefault(
            code, {"outcomes": [], "items_returned": 0, "succeeded": False, "failed_or_blocked": False}
        )
        entry["outcomes"].append(r["outcome"])
        entry["items_returned"] += int(r["items_returned"] or 0)
        entry["succeeded"] = entry["succeeded"] or r["outcome"] == "succeeded"
        entry["failed_or_blocked"] = entry["failed_or_blocked"] or r["outcome"] in UNAVAILABLE_OUTCOMES
    version_pins = {
        "ontology_version": manifest.ontology_version,
        "methodology_version": assessment.methodology_version,
        "ruleset_version": assessment.ruleset_version,
        "prompt_version": assessment.prompt_version,
        "model_id": assessment.model_id,
        "manifest_hash": manifest.hash,
    }
    payload = {
        "frozen_at": when.isoformat(),
        "link_states": link_states,
        "incident_states": incident_states,
        "target_states": target_states,
        "connector_runs": connector_runs,
        "version_pins": version_pins,
    }
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    snapshot = EvidenceSnapshot(
        assessment_id=assessment.id,
        frozen_at=when,
        manifest_hash=manifest.hash,
        span_ids=span_ids,
        link_ids=link_ids,
        link_states=link_states,
        incident_states=incident_states,
        target_states=target_states,
        connector_runs=connector_runs,
        version_pins=version_pins,
        snapshot_sha256=digest,
    )
    return store.insert(snapshot, reason="snapshot frozen before evaluation")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _target_states(conn: Connection, org_id: UUID) -> dict[str, Any]:
    """The organization's controls, tests, systems and impact measures, frozen for the verification rules."""
    params = {"org_id": org_id}
    controls = {
        str(r["id"]): {
            "name": r["name"],
            "ai_system_id": str(r["ai_system_id"]) if r["ai_system_id"] else None,
            "capabilities": [str(x) for x in (r["capabilities"] or [])],
            "monitoring_mode": r["monitoring_mode"],
            "operational_status": r["operational_status"],
            "can_pause_or_rollback": r["can_pause_or_rollback"],
        }
        for r in conn.execute(text(CONTROLS_QUERY), params).mappings().all()
    }
    tests = [
        {
            "id": str(r["id"]),
            "control_id": str(r["control_id"]),
            "result": r["result"],
            "method": r["method"],
            "capabilities_exercised": [str(x) for x in (r["capabilities_exercised"] or [])],
            "threats_exercised": [str(x) for x in (r["threats_exercised"] or [])],
            "performed_at": _iso(r["performed_at"]),
            "verifier_org_id": str(r["verifier_org_id"]) if r["verifier_org_id"] else None,
        }
        for r in conn.execute(text(TESTS_QUERY), params).mappings().all()
    ]
    systems = {
        str(r["id"]): {
            "name": r["name"],
            "autonomy_level": r["autonomy_level"],
            "monitoring_mode": r["monitoring_mode"],
            "criticality": r["criticality"],
        }
        for r in conn.execute(text(SYSTEMS_QUERY), params).mappings().all()
    }
    measures = [
        {
            "id": str(r["id"]),
            "kind": r["kind"],
            "outcome": r["outcome"],
            "verifier_org_id": str(r["verifier_org_id"]) if r["verifier_org_id"] else None,
            "measured_at": _iso(r["measured_at"]),
            "period_months": r["period_months"],
            "ai_system_id": str(r["ai_system_id"]) if r["ai_system_id"] else None,
        }
        for r in conn.execute(text(IMPACT_QUERY), params).mappings().all()
    ]
    return {"controls": controls, "test_outcomes": tests, "ai_systems": systems, "impact_measures": measures}


def load_snapshot(store: Store, assessment_id: UUID) -> EvidenceSnapshot | None:
    return store.first(EvidenceSnapshot, where={"assessment_id": assessment_id})
