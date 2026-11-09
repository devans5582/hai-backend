# 0016 The Seven Focus Areas And The Scoring Review

Status: accepted (2026-11-09); methodology content stays draft until Humaital signs.

## Context

Humaital asked for seven areas to be included in the ontology: verification of
AI controls, autonomous AI monitoring, containment and security testing,
evidence-based scoring, incident response and recovery, independent monitoring
and auditability, and human benefit with measurable impact. At the same time
the published HAI Report (Rubric v2, Microsoft, 2026-05-29) was reviewed
against the platform's scoring model. The report shows materiality-weighted
pillar means, stage-weighted pillar maxima, a four-part confidence
decomposition (40/30/20/10), pillar statuses with fixed wording, evidence
strength by class, and a headline score (85) that its own pillar scores (45.8)
do not support.

## Decisions

1. The seven areas are a vocabulary (`focus_area`), not new criteria or
   weights. Criteria list the areas they bear on, supporting links are tagged
   by lexicon, and the report shows coverage per area. Changing criteria or
   weights is Humaital's call (decision D12).
2. Structured evidence gets a home: control capabilities and the tests that
   exercised them, containment threats, autonomy and observability of systems,
   the incident response timeline, and the `ImpactMeasure` entity that
   separates stated intention from measured outcome. The snapshot freezes these
   rows as `target_states` so the rules still read only the snapshot.
3. Three rules act on that evidence. A claimed pause, shutdown, rollback or
   isolate capability without a passing exercise is capped at the documented
   control level (IC-19): the ladder already says documented execution needs
   dated results, this makes it bite for stop capabilities. An unverified
   correction and self-reported monitoring route to review; they do not move a
   level automatically.
4. Scoring aligns with the published report where the report is right and
   departs where it is not. Pillar means are materiality-weighted (the report
   reproduces only with the weights). Confidence is the published 40/30/20/10
   decomposition over frozen link attributes, with rung credits that rise
   strictly from statement to independent verification (change request point
   4). Pillar status follows the rung reached by half the criteria. Certification
   requires admissible evidence in every pillar. The headline score is the
   aggregate the pillars produce; a cap is shown as a cap. Stage-weighted
   pillar profiles are recorded (one profile is known) and not applied until
   Humaital supplies the rest (D11).
5. Versioning: ontology 1.1.0 (additive), methodology 2.0.0 (scoring,
   confidence and certification changed), ruleset 1.1.0. The applied baseline
   `0001` is frozen; codegen writes the current schema to `db/generated/` and
   `0004_ontology_1_1.sql` carries the delta. Relation extensions are minor.

## Consequences

* Reports and the console show evidence basis, pillar status, evidence
  strength, focus-area coverage, control verification, incident response and
  impact measures, all from stored rows.
* A website-only organization with policy quotes now lands near 40 percent
  confidence, which is what customers have seen in published reports.
* The public pipeline tags focus areas; the structured rows come from
  uploads, the API and reviewers, so the three new rules fire only when that
  evidence exists. This is deliberate: verification evidence is not inferred.
