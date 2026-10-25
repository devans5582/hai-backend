# ADR 0011: Extension Point: Peer Benchmarks

Status: accepted (2026-10-24)

## Context

Organizations want to know where they stand among peers.

## Decision

`hai_ops.v_industry_benchmarks` aggregates the latest result per organization
by industry, stage band and size band, excluding `access_limited` outcomes.
`GET /v1/benchmarks/industries` serves it. Individual organizations are never
exposed through the view.

## Consequences

Benchmarks are a read model with no new writes. Thresholds per stage and size
(decision D3) can use the same grouping when Humaital supplies a table.
