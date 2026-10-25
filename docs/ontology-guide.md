# Ontology Guide

How the manifest under `ontology/` is organised, how to read it, and how to
change it. The spec it models is `HAI_Ontology_v1_Specification (1).docx` at the repository root.

For the relationship diagrams and the full entity, relation, vocabulary and
rule tables generated from the manifest, read `ontology/README.md` first.

## Files

```
ontology/
  ontology.yaml              header, layers, roles, entities, fields, relations, IC-xx, AT-xx
  vocabularies/*.yaml        one closed vocabulary per file
  methodology/
    methodology.yaml         scoring, confidence, certification, outcome, freshness, review triggers, lexicons
    pillars.yaml             six pillars and weights
    criteria/<CODE>.yaml     one file per criterion
    rules.yaml               ruleset: codes, kinds, order, parameters, expression refs
    decisions.yaml           D1 to D10 with current behaviour
  examples/valid/*.json      records that must validate
  examples/invalid/*.json    records that must fail with the named error code
  CHANGELOG.md
```

Two vocabularies are derived, never hand-written: `criterion_code` comes
from `methodology/criteria/` and `pillar_code` from `methodology/pillars.yaml`.
The validator refuses a hand-written file with either name.

## Criterion Register

Codes are permanent. A retired code is never reused. Phase 6 IDs are kept as
`legacy_id` aliases. All rows are `content_status: draft` until Humaital
supplies the canonical definitions and level descriptors; the names, legacy
IDs and materiality weights are imported exactly from the Phase 6 code.

| # | Code | Pillar | Name | Legacy ID | Weight | Materiality | Freshness (months) |
|---|---|---|---|---|---|---|---|
| 1 | TRU-01 | TRU | User Confidence | trust_user_confidence | 1.0 | high (1.2) | 24 |
| 2 | TRU-02 | TRU | Consistency of Behavior | trust_consistency_of_behavior | 1.0 | standard (1.0) | 24 |
| 3 | TRU-03 | TRU | Ethical Intent | trust_ethical_intent | 1.0 | standard (1.1) | 24 |
| 4 | TRU-04 | TRU | Absence of Manipulation | trust_absence_of_manipulation | 1.0 | standard (1.1) | 24 |
| 5 | ACC-01 | ACC | Ownership of Outcomes | accountability_ownership_of_outcomes | 1.0 | high (1.4) | 24 |
| 6 | ACC-02 | ACC | Corrective Action | accountability_corrective_action | 1.0 | standard (1.1) | 24 |
| 7 | ACC-03 | ACC | Governance and Oversight | accountability_governance_and_oversight | 1.0 | high (1.3) | 24 |
| 8 | PUR-01 | PUR | Mission Clarity | purpose_mission_clarity | 1.0 | standard (0.9) | 24 |
| 9 | PUR-02 | PUR | Human-Centered Intent | purpose_human_centered_intent | 1.0 | standard (1.1) | 24 |
| 10 | PUR-03 | PUR | Alignment of Words and Actions | purpose_alignment_words_actions | 1.0 | standard (1.1) | 24 |
| 11 | SAF-01 | SAF | Risk Mitigation | safety_risk_mitigation | 1.0 | high (1.4) | 24 |
| 12 | SAF-02 | SAF | User Protection Mechanisms | safety_user_protection_mechanisms | 1.0 | high (1.3) | 24 |
| 13 | SAF-03 | SAF | Long-Term Societal Safety | safety_long_term_societal_safety | 1.0 | high (1.3) | 24 |
| 14 | TRN-01 | TRN | Explainability | transparency_explainability | 1.0 | high (1.2) | 24 |
| 15 | TRN-02 | TRN | Data Disclosure | transparency_data_disclosure | 1.0 | high (1.2) | 24 |
| 16 | TRN-03 | TRN | Communication Honesty | transparency_communication_honesty | 1.0 | standard (1.1) | 24 |
| 17 | IMP-01 | IMP | Positive Human Outcomes | impact_positive_human_outcomes | 1.0 | high (1.3) | 24 |
| 18 | IMP-02 | IMP | Shared Human Benefit | impact_shared_human_benefit | 1.0 | standard (1.0) | 24 |
| 19 | IMP-03 | IMP | Measurability of Impact | impact_measurability_of_impact | 1.0 | high (1.2) | 24 |
| 20 | IMP-04 | IMP | Durability of Impact | impact_durability_of_impact | 1.0 | standard (0.8) | 24 |

Weight is the within-pillar weight (all 1.0 in 1.0.0). The number in the
materiality column is the Phase 6 materiality weight used by confidence
(`legacy/express-api/src/services/evidence-weighting.js:51-96`); `high` means
1.2 or above. The test `test_register_matches_criteria_files` keeps this table
and the YAML in step.

## Pillars

| Code | Name | Weight | Phase 6 max points |
|---|---|---|---|
| TRU | Trust | 0.20 | 20 |
| ACC | Accountability | 0.15 | 15 |
| PUR | Purpose | 0.15 | 15 |
| SAF | Safety | 0.15 | 15 |
| TRN | Transparency | 0.15 | 15 |
| IMP | Impact | 0.20 | 20 |

## Per-Criterion Structure

```yaml
criterion:
  code: SAF-02
  pillar: SAF
  name: "User Protection Mechanisms"
  legacy_id: safety_user_protection_mechanisms
  content_status: draft           # draft | approved
  definition: "..."
  materiality: high               # high | standard (vocabulary materiality)
  materiality_weight: 1.3         # used by confidence; by score only when D2 says so
  weight: 1.0                     # within-pillar weight
  freshness_window_months: 24     # D8; admissibility stale window for dated evidence
  target_types: [organization, ai_system, control, test_outcome]
  applicability: []               # D5: list of {condition, effect}
  levels:                         # exactly five, monotonic rungs (D1)
    - {level: 1, required_maturity_rung: none, descriptor: "..."}
    - {level: 2, required_maturity_rung: stated_commitment, descriptor: "..."}
    - {level: 3, required_maturity_rung: specified_control, descriptor: "..."}
    - {level: 4, required_maturity_rung: documented_execution, descriptor: "..."}
    - {level: 5, required_maturity_rung: independently_verified, descriptor: "..."}
  retrieval_hints: ["safeguard", "user protection"]   # drive link proposals
  indicators:                     # Phase 6 rubric item ids; labels are drafts
    - {code: S2_R1, kind: legacy_r, label: null}
```

## Maturity Ladder

| Rung | Minimum evidence |
|---|---|
| none | A mention, title or metadata only. Never lifts a level. |
| stated_commitment | A quoted policy or statement by the organization. |
| specified_control | A quote naming an owner and a measurable threshold. |
| documented_execution | A quote with a dated test or monitoring result. Self-reported counts. |
| independently_verified | A span from a publisher whose independence is independent or regulator (IC-07). |

Source tier never sets maturity. The rules engine reads the rung from the
frozen link; the classifier set it from the quote and the publisher only.

## Coverage States

| State | In score | Report wording |
|---|---|---|
| observed | yes | Level and its evidence. |
| missing | yes, level 1 | Searched, not found. Not proof of absence. |
| unavailable | no | Access limitation, not a governance gap. Requires a failed or blocked connector run (IC-15). |
| not_applicable | no | Why it does not apply. |
| not_tested | yes | Control documented, operation unconfirmed. |
| failed | yes | The failed result and date. |
| contradictory | yes, routed to review | Both sides. |

## Acceptance Tests

`ontology.yaml` lists AT-01 to AT-15 with the test functions that prove each
one. The mapping is checked by `tests/test_acceptance_tests_are_mapped.py` and
rendered in `docs/architecture.md`.

## Crosswalks

`methodology/crosswalks.yaml` maps each criterion to clauses of the EU AI Act,
NIST AI RMF and ISO/IEC 42001 with a direction (covers, supports, informs). It
is a draft (`content_status: draft`, `TODO(humaital)`), is not part of the
manifest hash, and does not affect scoring. A test checks that every mapping
names a real criterion and framework.

## Changing The Manifest

1. Edit the YAML. Add a valid and an invalid example when a shape changes.
2. `make ontology-validate` then `make codegen`. Commit the generated files.
3. `make check-bump BASE=git:origin/main` reports whether the version moved
   far enough: patch for labels and wording, minor for a new value, optional
   field, entity or criterion, major for a removal, rename, type change, new
   required field, weight change or ladder change.
4. `make migrate-plan` emits additive SQL for minor changes and refuses
   breaking ones without `--allow-breaking`.
5. Record the change in `ontology/CHANGELOG.md`. A methodology content change
   needs a Humaital change record before `methodology.status` becomes
   approved. Rescoring under a new methodology is a new assessment; history is
   never edited.
