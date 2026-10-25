# ADR 0010: Extension Point: Score Explorer Through The Trace API

Status: accepted (2026-10-24)

## Context

Users need to see why a criterion got its level.

## Decision

Every `criterion_decision` and `assessment_result` stores a trace: inputs, each
rule in run order with the state before and after, caps and adjustments, the
finding used, and the links with quotes and offsets.
`GET /v1/assessments/{id}/trace` and `/trace/{criterion}` expose it; the
console's trace drawer renders it to the exact quote.

## Consequences

The score explorer is a client of stored data, so a future richer UI needs no
engine change. The trace is part of the replay comparison, so it cannot drift
from the result.
