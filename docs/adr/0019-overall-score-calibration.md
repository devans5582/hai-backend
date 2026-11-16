# Overall Score Calibration

Date: 2026-11-16

Status: Accepted implementation; methodology content remains draft.

## Request And Scope

After reviewing the low assessment scores, the owner requested that the
implementation make scores 4 to 5 times more generous. Use 4.5, the midpoint
of that range. This is a new draft calibration requested by the owner, not a
claim that the published Humaital methodology specifies this multiplier.
The evidence collection and classification corrections in ADR 0018 remain
in force.

## Decision

Keep the existing evidence-derived criterion levels, pillar scores and
weighted aggregate as the baseline. Apply the calibration to the overall
aggregate once, then round half up to one decimal and limit the result to
the 100-point scale. Apply the existing policy caps afterwards. Do not
multiply each pillar separately: capping pillars before aggregation would
produce a different overall multiplier.

For the same baseline, 5.3 becomes 23.9, 7.7 becomes 34.7, 7.4 becomes 33.3,
and 12.5 becomes 56.3. Zero remains zero and an unavailable score remains
unavailable. These are arithmetic examples, not reassessments of the
historical reports. One-decimal baselines of 22.3 and above reach 100, so
the ceiling compresses differences between higher baselines.

Configure the multiplier and baseline certification basis under
`scoring.calibration` in the manifest. Manifests that omit this optional
configuration default to a multiplier of 1. Store the actual baseline,
multiplier, calibrated value, ceiling, pillar basis and certification
threshold in new result traces. Include calibration metadata in calibrated
result hashes. Keep legacy hash behavior when the multiplier is 1.

Reports, the API and console render stored calibration metadata. They
identify pillar values as baseline scores and disclose the overall
transformation, without recalculating it in the browser or export renderer.
Confidence, effectiveness, coverage and maturity remain evidence-derived.
Certification compares the baseline with the existing stage threshold and
retains all confidence, evidence and human review requirements. Signing
also verifies the stored baseline threshold defensively.

## Versioning And History

Release the scoring change as methodology 4.0.0 and ruleset 3.0.0. Keep
ontology 1.3.0 because no ontology entity or vocabulary changes. Regenerate
manifest-derived artifacts and ship metadata migration
`0007_methodology_4.sql`.

New assessments receive the new version pins. Do not rewrite old scores or
infer calibration for historical results that lack stored metadata.
Existing replay guards reject mismatched manifests, and benchmarks remain
within compatible version cohorts. Reassess an organization to obtain a
new score under this release.

## Validation

Verify half-up rounding, the ceiling, zero, unavailable and partial-pillar
scores. Check that confidence and effectiveness stay unchanged, replay
hashes match and the stored score never exceeds database constraints.
Test that an uplifted 100 with a baseline below the stage threshold cannot
qualify for certification. Exercise API, report and PDF disclosure, legacy
exports and frontend rendering. Run the generated-artifact and version
gates, unit tests, frontend checks and PostgreSQL suites with roles enabled
and disabled.
