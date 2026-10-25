# ADR 0003: The Evidence Link Is The Only Bridge To A Score

Status: accepted (2026-10-24)

## Context

Phase 6 used site-wide keyword counts, took the best "proof of execution" found
anywhere as a global multiplier, and treated the existence of a Wayback
snapshot as support for every criterion.

## Decision

Nothing reaches a score except through an `evidence_link` that names exactly
one `evidence_span`, one target (organization, AI system, claim, control, test
outcome or incident) and one criterion. The link carries the six judgments
(polarity, admissibility, maturity rung, execution level, evidence class,
independence) plus source tier. Polarity is immutable after insert (IC-01).
A link counts only for the criterion it names (IC-08). Spans must match the
stored document text at their offsets (IC-03) and metadata alone never lifts
maturity above `none` (IC-06).

## Consequences

Every number in a report can be followed to a quote with character offsets in a
stored document fetched by a recorded connector run. Execution evidence is per
span, so one strong page cannot inflate twenty criteria.
