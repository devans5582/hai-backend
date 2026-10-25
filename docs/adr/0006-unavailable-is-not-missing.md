# ADR 0006: Unavailable Is Not Missing

Status: accepted (2026-10-24)

## Context

Phase 6 scored a blocked website as missing evidence, so an organization with
a strict robots policy received the same score as one with no governance at all
(AT-11).

## Decision

Coverage state is a first-class vocabulary. `unavailable` is set only when a
primary connector run failed or was blocked (IC-15) and no evidence was found
elsewhere; it excludes the criterion from the score instead of zeroing it.
`missing` means the sources were searched and nothing was found; it counts
against the score. Reports list only sources with a succeeded connector run
(IC-16) and render the stored coverage wording.

## Consequences

Access-limited runs produce the `access_limited` outcome and are excluded from
peer benchmarks. Every connector runs on every assessment and every run is
recorded (AT-01), which is what makes the distinction provable.
