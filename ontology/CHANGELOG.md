# Ontology Changelog

All notable changes to the manifest under `ontology/`. The ontology and the
methodology are versioned separately with semver. A diff tool classifies each
change (patch, minor, major) and CI refuses a version that did not move far
enough.

## Ontology 1.1.0, Methodology 2.0.0, Ruleset 1.1.0 (2026-11-09)

Change request of 2026-11-09 (seven focus areas) and the scoring review
against the published HAI Report (Rubric v2). ADR 0016. Methodology status
stays draft until Humaital signs the change record.

Ontology (minor, additive; delta in `db/migrations/0004_ontology_1_1.sql`):

* Eight vocabularies: `focus_area` (the seven areas), `control_capability`,
  `verification_method`, `containment_threat`, `autonomy_level`,
  `observability`, `impact_evidence_kind`, `maturity_status`.
* `ImpactMeasure` entity (31 entities) with relations `measures`,
  `measured_by` and `reported_in`; `impact_measure` added to `target_type`
  and `claim_scope_type`.
* Fields: `Control.capabilities`, `monitoring_mode`, `last_exercised_at`;
  `TestOutcome.method`, `capabilities_exercised`, `threats_exercised`;
  `AISystem.autonomy_level`, `monitoring_mode`; the incident response
  timeline on `Incident` (`detected_at`, `disclosed_at`, `contained_at`,
  `corrected_at`, `correction_verified_at`, `correction_verified_by_org_id`,
  `containment_threat`); `EvidenceLink.focus_area`;
  `EvidenceSnapshot.target_states`; `PillarScore.status`.
* IC-19 (verification over assertion) and AT-16.
* `db/migrations/0001` is now frozen; codegen writes the full current schema
  to `db/generated/ontology_schema.sql` for reference and new versions ship
  numbered deltas from `hai-ontology migrate-plan`.

Methodology (major: scoring, confidence and certification changed):

* `scoring.pillar_aggregation` is `materiality_weighted`, as the published
  report computes pillar scores (decision D2 updated).
* `scoring.pillar_weight_profiles` records the mature-stage profile observed
  in the report; mode `fixed` until the other profiles are known (D11).
* `confidence.model` is `components`: source credibility 40, evidence type
  30, cross-source validation 20, recency 10, the decomposition every HAI
  Report publishes; rung credits for the evidence type component rise
  strictly from stated commitment to independent verification (D13).
* `certification.require_evidence_in_every_pillar` (the report's
  "documented evidence across all pillars").
* `report.evidence_strength_labels` and pillar `maturity_status`, with the
  report's status wording.
* Criteria list `focus_areas` (draft cross-reference, D12); Impact criteria
  accept `impact_measure` targets; focus-area lexicons.

Ruleset 1.1.0: `CAP-UNEXERCISED-CAPABILITY`, `GATE-INCIDENT-RESPONSE`,
`GATE-SELF-REPORTED-MONITORING` (19 rules). Decisions D11 to D13 added.

## Ontology 1.0.0, Methodology 1.0.0 (2026-10-24)

First release, modelled from `HAI_Ontology_v1_Specification (1).docx` at the
repository root.

* Four layers, 30 entities, the relationship catalogue, 34 hand-written
  vocabularies plus the two derived ones (`criterion_code`, `pillar_code`).
* Integrity constraints IC-01 to IC-18 and acceptance tests AT-01 to AT-15.
* Six pillars with the Phase 6 weights.
* Twenty criteria with codes `PIL-NN`, Phase 6 IDs as aliases. Definitions,
  level descriptors and indicator labels are drafts (`content_status: draft`,
  `TODO(humaital)`).
* Ruleset 1.0.0 with 16 rules.
* Open decisions D1 to D10 with current behaviour.
* Acceptance tests AT-01 to AT-15 name the test functions that prove them; a
  unit test fails when a named function does not exist.
* `methodology/crosswalks.yaml` added as a draft mapping to the EU AI Act,
  NIST AI RMF and ISO/IEC 42001 (not part of the manifest hash, no effect on
  scoring, `TODO(humaital)`).
