# ADR 0002: The Model Proposes, The Rules Decide, A Reviewer Signs

Status: accepted (2026-10-24)

## Context

In Phase 6 the model's JSON set the score directly (`openai.js`), the browser
recomputed scores, and nobody signed anything. Scores could not be reproduced
or defended.

## Decision

Three authorities, strictly separated:

* The LLM (or the offline heuristic provider) produces `criterion_findings`
  that are advisory. A finding may cite only spans and links inside the
  assessment's frozen snapshot (IC-04, IC-05) and is rejected otherwise.
* The rules engine (`hai_engine.rules`) reads only the frozen
  `evidence_snapshot` and the manifest, runs the ruleset in order, and is the
  only writer of `criterion_decisions`, `pillar_scores` and
  `assessment_results` (IC-12, enforced by database grants). Every decision
  lists the rules that produced it (IC-14) and a trace of before and after
  values.
* A named reviewer with a reviewer JWT signs `certification_decisions`. An
  `assessment_result` with `hai_certified` cannot exist without a signed row
  (IC-13, constraint trigger). API keys are refused (AT-10).

Replay recomputes the result from the stored snapshot and must reproduce the
stored `result_sha256` (AT-07).

## Consequences

Any score can be explained rule by rule and reproduced later under the pinned
versions. Model upgrades change proposals, not the decision procedure. The
browser renders stored values and never computes.
