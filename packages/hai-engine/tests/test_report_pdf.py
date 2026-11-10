"""The PDF rendering of a report: every section renders from the report dictionary alone."""

from __future__ import annotations

from typing import Any

from hai_core.generated.enums import (
    Admissibility,
    CertificationOutcome,
    CoverageState,
    MaturityRung,
    MaturityStatus,
    OutcomeStatus,
    Polarity,
)
from hai_engine.report_pdf import build_pdf, render_report_pdf, report_filename

RUNGS = [r.value for r in MaturityRung]


def _link(quote: str, rung: str, **over: Any) -> dict[str, Any]:
    base = {
        "link_id": "l1",
        "quote": quote,
        "polarity": Polarity.SUPPORTS.value,
        "admissibility": Admissibility.ADMISSIBLE.value,
        "maturity_rung": rung,
        "execution_level": "asserted",
        "evidence_class": "core_governance",
        "independence": "self",
        "source_tier": "T1",
        "publisher_name": "Acme Corp",
        "publisher_type": "org_disclosure",
        "published_at": "2026-01-10",
        "canonical_url": "https://www.acme.example/responsible-ai",
        "document_title": "Responsible AI at Acme",
        "section_heading": None,
        "document_id": "doc-1",
        "span_id": "span-1",
        "char_start": 0,
        "char_end": 40,
        "target_type": "organization",
        "target_id": "org-1",
        "focus_area": "control_verification",
    }
    base.update(over)
    return base


def sample_report(*, with_result: bool = True) -> dict[str, Any]:
    labels = {
        RUNGS[0]: "None",
        RUNGS[1]: "Stated commitment",
        RUNGS[2]: "Specified control",
        RUNGS[3]: "Documented execution",
        RUNGS[4]: "Independently verified",
    }
    criteria = [
        {
            "code": "SAF-01",
            "name": "Risk Mitigation",
            "pillar": "SAF",
            "definition": "d",
            "content_status": "draft",
            "level": 3,
            "level_descriptor": "A named risk process with dated results.",
            "coverage_state": CoverageState.OBSERVED.value,
            "coverage_wording": "Assessed from admissible evidence.",
            "confidence": 71.5,
            "review_required": False,
            "applied_rule_codes": ["GATE-COVERAGE"],
            "evidence": [
                _link("We run a quarterly model risk review with été résultats — and “quotes”.", RUNGS[3]),
                _link("We are committed to safe AI.", RUNGS[1], link_id="l2", polarity=Polarity.CONTRADICTS.value),
            ],
            "evidence_basis": {RUNGS[3]: 1},
            "best_rung": RUNGS[3],
            "focus_areas": ["control_verification"],
            "confidence_components": {},
            "decision_id": "d1",
        },
        {
            "code": "SAF-02",
            "name": "User Protection Mechanisms",
            "pillar": "SAF",
            "definition": "d",
            "content_status": "draft",
            "level": None,
            "level_descriptor": None,
            "coverage_state": CoverageState.UNAVAILABLE.value,
            "coverage_wording": "Sources could not be reached.",
            "confidence": 0,
            "review_required": True,
            "applied_rule_codes": [],
            "evidence": [],
            "evidence_basis": {},
            "best_rung": None,
            "focus_areas": [],
            "confidence_components": {},
            "decision_id": "d2",
        },
        {
            "code": "TRU-01",
            "name": "User Confidence",
            "pillar": "TRU",
            "definition": "d",
            "content_status": "draft",
            "level": 2,
            "level_descriptor": "A stated commitment.",
            "coverage_state": CoverageState.OBSERVED.value,
            "coverage_wording": "Assessed from admissible evidence.",
            "confidence": 40,
            "review_required": False,
            "applied_rule_codes": [],
            "evidence": [
                _link(
                    "We are committed to user trust.",
                    RUNGS[1],
                    document_id="doc-2",
                    canonical_url="https://news.example/acme",
                    publisher_name="News",
                    publisher_type="press",
                )
            ],
            "evidence_basis": {RUNGS[1]: 1},
            "best_rung": RUNGS[1],
            "focus_areas": [],
            "confidence_components": {},
            "decision_id": "d3",
        },
    ]
    result = {
        "hai_score": 42.5,
        "confidence_pct": 61.2,
        "effectiveness": 25,
        "outcome_status": OutcomeStatus.CONFIDENCE_TOO_LOW.value,
        "outcome_label": "Confidence too low",
        "gate_reasons": ["confidence 61.2 below minimum 70"],
        "review_triggers": ["incident:unverified_correction"],
        "caps_applied": ["CAP-UNEXERCISED-CAPABILITY"],
        "score_before_caps": 44.0,
        "result_id": "r1",
        "result_sha256": "ab" * 32,
    }
    return {
        "product": {"report_name": "HAI Score", "long_name": "Human Alignment Index"},
        "scale": {"level_max": 5, "score_scale": 100, "certification_threshold": 70, "min_confidence": 70},
        "version": {"number": 2, "total": 3},
        "assessment": {
            "id": "11111111-1111-4111-8111-111111111111",
            "lifecycle_state": "completed_unverified",
            "lifecycle_label": "Completed (unverified)",
            "requested_by": "api_key:partner",
            "submitted_domain": "acme.example",
            "stage_band": "growth",
            "size_band": "mid",
            "versions": {
                "ontology": "1.2.0",
                "methodology": "2.0.0",
                "ruleset": "1.1.0",
                "prompt": "1.0.0",
                "model": "heuristic:ladder-1",
            },
            "created_at": "2026-11-01T12:00:00+00:00",
            "finished_at": "2026-11-01T12:30:00+00:00",
        },
        "organization": {
            "id": "org-1",
            "name": "Acme Corp",
            "legal_name": "Acme Corporation",
            "domain": "acme.example",
            "industry_code": "technology",
        },
        "result": result if with_result else None,
        "certification": {
            "decision": CertificationOutcome.NOT_CERTIFIED.value,
            "decision_label": "Not certified",
            "certificate_number": None,
            "reviewer_id": "rev-1",
            "signed_at": "2026-11-02T09:00:00+00:00",
            "expires_at": None,
            "threshold_applied": 70,
            "gate_reasons": ["confidence 61.2 below minimum 70"],
        }
        if with_result
        else None,
        "benchmark": {
            "industry_code": "technology",
            "industry_label": "Technology",
            "organizations": 4,
            "average_score": 38.0,
            "average_confidence": 55.0,
            "position": "above",
        },
        "pillars": [
            {
                "code": "TRU",
                "name": "Trust",
                "weight": 0.18,
                "score": 50,
                "confidence": 60,
                "criteria_counted": 4,
                "criteria_excluded": 0,
                "status": MaturityStatus.DEVELOPING.value,
                "status_label": "Developing",
                "status_wording": "Evidence exists at policy level but lacks execution proof.",
            },
            {
                "code": "SAF",
                "name": "Safety",
                "weight": 0.18,
                "score": 33.3,
                "confidence": 70,
                "criteria_counted": 2,
                "criteria_excluded": 1,
                "status": MaturityStatus.PROGRESSING.value,
                "status_label": "Progressing",
                "status_wording": "Policy and partial execution evidence present; gaps remain.",
            },
        ],
        "criteria": criteria,
        "evidence_classes": [
            {"code": "core_governance", "label": "Core governance", "description": "Policy, statement or commitment."},
            {
                "code": "operational_evidence",
                "label": "Operational evidence",
                "description": "Process, control, metric or dated record.",
            },
        ],
        "status_definitions": [
            {
                "code": MaturityStatus.NEEDS_ATTENTION.value,
                "label": "Needs Attention",
                "wording": "No verifiable evidence found.",
            },
            {
                "code": MaturityStatus.DEVELOPING.value,
                "label": "Developing",
                "wording": "Evidence exists at policy level.",
            },
        ],
        "rung_definitions": [{"code": code, "label": label, "description": ""} for code, label in labels.items()],
        "evidence_basis": {
            "by_rung": {RUNGS[0]: 0, RUNGS[1]: 1, RUNGS[2]: 0, RUNGS[3]: 1, RUNGS[4]: 0},
            "labels": labels,
            "criteria_counted": 2,
        },
        "evidence_strength": {
            "core_governance": {
                "label": "Core governance",
                "criteria_with_evidence": 1,
                "share": 0.5,
                "strength": "Emerging",
            }
        },
        "focus_areas": [
            {
                "code": "control_verification",
                "label": "Verification of AI controls",
                "question": "Do the controls work?",
                "cross_cutting": False,
                "criteria": ["SAF-01"],
                "links": 1,
                "by_rung": {RUNGS[3]: 1},
                "best_rung": RUNGS[3],
                "best_rung_label": "Documented execution",
            },
            {
                "code": "human_benefit",
                "label": "Human benefit and measurable impact",
                "question": "Is benefit measured?",
                "cross_cutting": False,
                "criteria": ["IMP-01"],
                "links": 0,
                "by_rung": {},
                "best_rung": None,
                "best_rung_label": None,
            },
        ],
        "verification": {
            "controls": [
                {
                    "control_id": "c1",
                    "name": "Kill switch",
                    "claimed_capabilities": ["pause", "shutdown"],
                    "exercised_capabilities": ["pause"],
                    "unexercised_capabilities": ["shutdown"],
                    "monitoring_mode": "operator_logs",
                    "operational_status": "operational",
                    "tests": 1,
                }
            ],
            "tests_by_method": {"live_drill": 1},
            "threats_exercised": {"safeguard_disablement": 1},
            "ai_systems": [
                {
                    "system_id": "s1",
                    "name": "Assistant",
                    "autonomy_level": "supervised",
                    "monitoring_mode": "operator_logs",
                    "criticality": "high",
                }
            ],
            "controls_with_unexercised_capabilities": 1,
        },
        "incident_response": [
            {
                "incident_id": "i1",
                "title": "Model outage",
                "status": "remediating",
                "severity": "high",
                "containment_threat": None,
                "days_to_disclose": 2,
                "days_to_contain": 1,
                "days_to_correct": None,
                "correction_verified": False,
            }
        ],
        "impact_measures": {
            "items": [
                {
                    "id": "m1",
                    "kind": "outcome_metric",
                    "kind_label": "Outcome metric",
                    "outcome": "Fewer appeals",
                    "measured_at": "2026-03-01",
                    "period_months": 6,
                    "verified_independently": False,
                    "demonstrates_benefit": True,
                }
            ],
            "by_kind": {"outcome_metric": 1},
            "demonstrated_benefit": 1,
            "total": 1,
        },
        "confidence_methodology": {
            "model": "components",
            "source": "HAI Report (Rubric v2)",
            "weights": {
                "source_credibility": 0.4,
                "evidence_type": 0.3,
                "cross_source_validation": 0.2,
                "recency": 0.1,
            },
            "evidence_type_credit": {RUNGS[1]: 0.4, RUNGS[3]: 0.8},
        },
        "coverage_summary": {CoverageState.OBSERVED.value: 2, CoverageState.UNAVAILABLE.value: 1},
        "connector_runs": [
            {
                "code": "website",
                "name": "Corporate website",
                "outcome": "succeeded",
                "items_returned": 3,
                "error_code": None,
                "started_at": None,
                "finished_at": None,
                "notes": None,
            },
            {
                "code": "regulators",
                "name": "Regulatory filings",
                "outcome": "blocked",
                "items_returned": 0,
                "error_code": "http_403",
                "started_at": None,
                "finished_at": None,
                "notes": None,
            },
        ],
        "sources": [
            {
                "id": "doc-1",
                "canonical_url": "https://www.acme.example/responsible-ai",
                "title": "Responsible AI at Acme",
                "published_at": "2026-01-10",
                "retrieved_at": None,
                "publisher": "Acme Corp",
                "publisher_type": "org_disclosure",
                "connector": "website",
                "run_outcome": "succeeded",
                "cluster_id": None,
                "sha256": "x",
            },
            {
                "id": "doc-3",
                "canonical_url": "https://www.acme.example/careers",
                "title": "Careers",
                "published_at": None,
                "retrieved_at": None,
                "publisher": "Acme Corp",
                "publisher_type": "org_disclosure",
                "connector": "website",
                "run_outcome": "succeeded",
                "cluster_id": None,
                "sha256": "y",
            },
        ],
        "execution_notes": [
            {
                "code": "TRU-01",
                "name": "User Confidence",
                "note": "Governance documentation was found but no artefact showing the practice operated was found.",
            }
        ],
        "snapshot": {"id": "snap-1", "frozen_at": "2026-11-01T12:05:00+00:00", "sha256": "cd" * 32, "links": 3},
        "drafts_notice": "Criterion definitions marked draft are placeholders.",
    }


def test_pdf_renders_every_section_from_the_report() -> None:
    pdf = build_pdf(sample_report())
    # cover, how evaluated, snapshot, two pillar pages, verification, evidence, gaps, appendix
    assert pdf.page_no() >= 9
    data = render_report_pdf(sample_report(), website="example.test", tagline="Tagline")
    assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    assert len(data) > 20_000


def test_pdf_without_a_result_still_renders() -> None:
    data = render_report_pdf(sample_report(with_result=False))
    assert data.startswith(b"%PDF-")


def test_filename_names_the_organization_and_version() -> None:
    assert report_filename(sample_report()) == "HAI-Score-Acme-Corp-v2.pdf"
    assert (
        report_filename(
            {"organization": {"name": "A/B & C"}, "version": {"number": 1}, "product": {"report_name": "HAI Score"}}
        )
        == "HAI-Score-A-B-C-v1.pdf"
    )
