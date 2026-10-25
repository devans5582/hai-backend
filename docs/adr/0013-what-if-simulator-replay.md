# ADR 0013: Extension Point: What-If Simulator Through Replay

Status: accepted (2026-10-24)

## Context

Methodology changes should be tested against real evidence before release.

## Decision

`DecisionService.replay` runs the engine over a stored snapshot without
writing. It accepts a manifest, so a candidate methodology (a `git:<ref>` or a
directory) can be replayed against existing snapshots and compared with the
stored results. Nothing is persisted and version pins are untouched.

## Consequences

The simulator is a loop over snapshots calling `replay` with another manifest;
a CLI or an endpoint can wrap it later without touching the engine.
