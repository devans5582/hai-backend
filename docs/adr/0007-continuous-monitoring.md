# ADR 0007: Extension Point: Continuous Monitoring

Status: accepted (2026-10-24)

## Context

Section 14 asks for continuous monitoring without a rewrite.

## Decision

`hai_ops.monitoring_subscriptions` holds one row per organization with a
cadence. The worker enqueues a `monitoring_tick` job once per interval
(deduplicated per minute bucket); the handler starts a reassessment for every
subscription that is due. Reassessments are ordinary assessments with
`parent_assessment_id` set, so trend views are a query over results.

## Consequences

Monitoring reuses the whole pipeline and all integrity constraints. Adding
change detection later means comparing the latest two results for an
organization, which `hai_ops.v_latest_results` already supports.
