# ADR 0004: Database Roles, Row-Level Security And Integrity Triggers

Status: accepted (2026-10-24)

## Context

Application-level checks are bypassable by any component holding the database
URL. The spec puts several integrity constraints in the database.

## Decision

Five NOLOGIN roles (`hai_pipeline`, `hai_engine`, `hai_reviewer`, `hai_api`,
`hai_admin`) with grants generated from each entity's `writers` list. Every
transaction runs `SET LOCAL ROLE` to the acting component when
`HAI_ENFORCE_DB_ROLES=true` and sets `hai.actor` for the audit log. Result
tables carry row-level security. Generated triggers enforce append-only tables
(IC-02), immutable columns (IC-01), state transitions from the vocabularies, and
the certification rule (IC-13). CHECK constraints are generated from the
vocabulary enums and the `py`/`sql` predicates on the entity checks.

## Consequences

The test suite runs twice in CI, with roles off and enforced, so a missing
grant fails before release. Hand-written migrations after the baseline must
keep grants in step; `0002_operations.sql` shows the pattern.
