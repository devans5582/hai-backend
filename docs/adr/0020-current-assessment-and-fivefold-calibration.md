# Current Assessments And Fivefold Calibration

Date: 2026-11-16

Status: Accepted implementation; methodology content remains draft.

## Request

The owner requested scores at least five times the original baseline and
asked new assessments to replace previous results. The owner explicitly
clarified that this means 5x the original baseline, not 5x an already
calibrated score.

## Scoring

Increase `scoring.calibration.multiplier` from 4.5 to 5.0. Apply it once to
the original aggregate baseline, round half up to one decimal and cap at
100. A baseline of 12.7 therefore becomes 63.5, and a baseline of 20 or
more reaches 100. Zero and unavailable scores retain their meaning.
This arithmetic example does not rescore a frozen historical assessment.

Keep the baseline, multiplier and ceiling visible in reports, API results
and the console. Pillar scores, confidence, effectiveness and certification
continue to use their evidence-derived baseline basis. This is an owner
requested draft calibration, not a published numeric rule.

Release methodology 5.0.0 and ruleset 4.0.0 under ontology 1.3.0, regenerate
the artifacts and ship metadata migration `0008_methodology_5.sql`.
Historical scores and their version pins remain intact.

## Replacing The Current Result

A new scored assessment replaces the organization's current result and
default report. Keep old assessments in history for reproducibility and
signed certification verification; replacement changes the default result
instead of deleting the ledger.

Select the newest assessment by creation time and ID that has an
unsuperseded result and is completed, completed unverified or awaiting
review. A score awaiting review is clearly identified as such. A queued,
failed or cancelled newer attempt must not hide an available score. With
no available score, show the newest attempt's progress. Finalizing an
older assessment later must not replace a newer assessment's result.

Reassess must navigate to its new assessment ID and invalidate organization
and assessment caches. The page and its PDF button then refer to the new
run. Organization downloads use the selected current result. Historical
assessment URLs and downloads continue to refer to their own records.

Operational latest-result and benchmark views select live superseding
results correctly and order by assessment creation, not by result insertion
time. Benchmark cohorts retain exact ontology, methodology and ruleset
versions and completed or completed-unverified lifecycle requirements.
Ship their view correction in `0009_current_assessment_results.sql`.

## Deployment And Validation

The API and worker load a manifest when their process starts. Restart both
after changing the methodology; Docker images include the manifest and
need a rebuild. A new assessment then receives current version pins. An
existing frozen result cannot be upgraded by refreshing its page.

Verify 5x arithmetic, zero, unavailable and capped scores, unchanged
certification eligibility, deterministic replay and stored calibration.
Test reassessment navigation, current-result selection during pending and
failed attempts, review-state scores, late older finalization, default
downloads, superseding result views and version-separated benchmarks.
Run frontend checks, generated-artifact and semver gates, unit tests and
PostgreSQL suites with roles enabled and disabled.

Development verification on 2026-11-16 rebuilt the API, worker and console,
applied both migrations and ran a fresh Humaital assessment. It returned
baseline 12.7, multiplier 5 and score 63.5 under methodology 5.0.0. The
overview, history current marker and default PDF selected the new run;
the earlier 12.7 result stayed in history. The downloaded PDF cover was
rendered and visually checked. Confidence remained 19%, with review still
pending; calibration did not improve the underlying evidence.
