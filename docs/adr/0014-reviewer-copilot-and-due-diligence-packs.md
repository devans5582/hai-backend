# ADR 0014: Extension Point: Reviewer Copilot And Due Diligence Packs

Status: accepted (2026-10-24)

## Context

Reviewers spend time reading evidence; buyers want a packaged report.

## Decision

Both are consumers of existing data. The reviewer copilot would read the trace,
the evidence pack and the review task and produce suggested reasons; it must
not act, because every review carries a named reviewer and a reason
(AT-14). Due diligence packs are the report JSON (`build_report`) plus the
sources list rendered to PDF or a document; the report already contains
every stored value, source and connector run.

## Consequences

Neither feature needs a schema change. Both are gated behind the same
authorization model as the console.
