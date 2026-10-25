# ADR 0008: Extension Point: Evidence Portal, Uploads As Claims

Status: accepted (2026-10-24)

## Context

Organizations will want to submit documents that are not public.

## Decision

Uploads (`POST /v1/evidence/uploads`) are stored in the blob store and recorded
in `hai_ops.uploads`; the `UPLOAD` connector turns them into source documents
with publisher type `org_disclosure`, independence `self` and source tier T4.
They therefore enter as claims: they can raise maturity to `stated_commitment`
or `specified_control` but never to `independently_verified` (IC-07), and they
carry no independence credit.

## Consequences

No special scoring path exists for submitted evidence; it flows through the same
links and rules. A reviewer can still route a link to review and approve it.
