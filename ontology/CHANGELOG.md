# Ontology Changelog

All notable changes to the manifest under `ontology/`. The ontology and the
methodology are versioned separately with semver. A diff tool classifies each
change (patch, minor, major) and CI refuses a version that did not move far
enough.

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
