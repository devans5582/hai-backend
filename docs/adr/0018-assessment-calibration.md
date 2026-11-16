# Assessment Calibration From The Validation Reports

Date: 2026-11-16

Status: Accepted implementation corrections; methodology content remains draft.

## Evidence

The nine assessment PDFs and preliminary developer findings in the shared
[PDF Reports folder](https://drive.google.com/drive/u/0/folders/1elrCaxB8ko1g0JhPPrjKyGJcvgD1K5KR)
show collection, classification, relevance and provenance defects. All reports
pin ontology 1.2.0, methodology 2.0.0, ruleset 1.1.0 and heuristic:ladder-1.
The [validation review](../assessment-validation-2026-11-16.md) records every
report, its source hash, the eight investigation requests and the limitations.

The live [scoring methodology](https://humaital.com/rating-scoring/) and
[assessment process](https://humaital.com/how-hai-assessment-works/) describe
Methodology v3.0, effective November 2026. They separate alignment from
confidence, describe a 100-point scale, retain weights of 20% for Trust and
Impact and 15% for each other pillar, and specify stage thresholds of 65 for
early organizations and 70 for growth and mature organizations. Documented
controls include defined procedures and assigned responsibilities, without
requiring a numeric threshold in every procedure.

The website does not provide a new numeric criterion curve, all detailed level
descriptors or a complete numeric confidence specification. Older cached
versions of the page contain obsolete tier multipliers; those are not used.

## Decision

Fix the evidence path before attributing the observed low scores to weights.
No overall score cap applied to any of the five numeric reports. Recognize
direct mission and governance statements, and controls supported by defined
procedures. Higher levels still require substantive operational results and
independent verification. General descriptions of what other organizations
should do do not establish the assessed organization's implementation.

Collect governance pages beyond the homepage, preserve article introductions,
and search current filings before stale ones. Empty or JavaScript-only primary
pages are collection failures, distinct from readable pages with no matching
evidence. Optional connectors returning no inputs are allowed to return zero.
Freshness windows are retained. Anti-bot access limitations remain visible.

Require a local AI connection and an actual, criterion-relevant negative event.
Generic environmental proceedings, legal navigation and hypothetical risk
warnings cannot become AI incidents across every criterion. SEC-hosted annual
reports and proxies remain issuer disclosures; hosting does not independently
verify their claims. Allegations still route to review.

Align supported configuration under ontology 1.3.0, methodology 3.0.0 and
ruleset 2.0.0: fixed published pillar weights, the full 100-point range, no
confidence-based alignment haircut, and the complete 65/70/70 stage table.
Confidence, evidence in every pillar and a named human reviewer remain
certification requirements. Preserve the existing criterion curve, materiality
weights and missing-evidence denominator pending a canonical replacement.

## Historical Results And Comparisons

Ship a numbered additive migration and regenerated artifacts. Seed the new
methodology alongside previous versions. Never replace the nine reports or
rewrite their results to achieve a preferred score. A new assessment receives
new pins and fresh evidence. The current engine refuses to replay, finalize
or sign a mismatched historical release; use that release for historical
replay. Historical exports identify current explanatory catalog limitations.

Partial-pillar scores renormalize available weights. Report the excluded
criteria and limit comparisons accordingly. Benchmarks must use compatible
ontology, methodology and ruleset versions and include finalized superseding
results rather than their superseded predecessors.

## Validation And Remaining Limits

Use the report's direct mission, oversight, recycling warning, SEC filing and
empty-content examples as regression cases. Check current-file selection,
source independence, quote offsets, version isolation, stage thresholds and
certification separately. Re-run PostgreSQL tests with roles enabled and
disabled, generated-artifact checks and the console gate.

The PDFs truncate evidence and do not contain full frozen records. They cannot
produce an exact historical replay or trustworthy new scores for the nine
organizations. The earlier Delta 65.8 report and error screenshot are absent.
The submitted Phizer/phizer.com identity requires correction by its submitter;
the pipeline must not silently substitute Pfizer. Do not promise that every
new score will rise: corrections remove unsupported positive evidence too.
