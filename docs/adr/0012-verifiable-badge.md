# ADR 0012: Extension Point: Verifiable Badge With Expiry

Status: accepted (2026-10-24)

## Context

A certification must be checkable by anyone, including after the organization
changes.

## Decision

A signed `certification_decision` gets a certificate number and an HMAC
signature over the decision, the result hash and the expiry. `GET
/v1/certifications/{number}/verify` is public and reports valid, expired,
revoked or not found with the score at signing. The console's Verify page
calls it.

## Consequences

Badges can link to the verify page. Revocation supersedes the decision and the
verify endpoint reflects it immediately. Rotating the signing key requires a
re-sign or a key id in the signature, which is the planned follow-up.
