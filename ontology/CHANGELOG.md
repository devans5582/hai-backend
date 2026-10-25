# Ontology Changelog

All notable changes to the manifest under `ontology/`. The ontology and the
methodology are versioned separately with semver. A diff tool classifies each
change (patch, minor, major) and CI refuses a version that did not move far
enough.

## Ontology 1.0.0, Methodology 1.0.0 (2026-10-24)

First release, modelled from `docs/spec/HAI_Ontology_v1_Specification.docx`.

* Four layers, 30 entities, the relationship catalogue, 33 hand-written
  vocabularies plus the two derived ones (`criterion_code`, `pillar_code`).
* Integrity constraints IC-01 to IC-18 and acceptance tests AT-01 to AT-15.
* Six pillars with the Phase 6 weights.
* Twenty criteria with codes `PIL-NN`, Phase 6 IDs as aliases. Definitions,
  level descriptors and indicator labels are drafts (`content_status: draft`,
  `TODO(humaital)`).
* Ruleset 1.0.0 with 16 rules.
* Open decisions D1 to D10 with current behaviour.
