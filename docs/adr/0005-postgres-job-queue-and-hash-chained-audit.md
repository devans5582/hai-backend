# ADR 0005: Postgres Job Queue And Hash-Chained Audit Log

Status: accepted (2026-10-24)

## Context

The platform needs background work (acquire, classify, freeze, evaluate,
decide, finalize, deliver webhooks, monitoring tick) and a tamper-evident
record of every write. Adding a broker and a separate log store would double the
operational surface for a v1.

## Decision

Jobs live in `hai_ops.jobs` and are claimed with `FOR UPDATE SKIP LOCKED`,
leased, deduplicated by key, retried with backoff and parked as `dead` after
the last attempt; a dead job fails its assessment. Audit events live in
`hai.audit_events`, each carrying the SHA-256 of the previous event under an
advisory lock, so `hai-db verify-audit` detects any edit or deletion (AT-15).

## Consequences

One database to run, back up and reason about. Throughput is bounded by
Postgres, which is ample for assessment volumes. If a broker is needed later,
`hai_core.queue.JobQueue` is the only module to replace.
