# 0015 Console Accounts, Roles And Organization Visibility

Status: accepted (2026-11-09)

## Context

Until now the console accepted a pasted API key or an admin-minted reviewer
token. There was no sign-in page, no notion of a user, no way for Humaital to
invite people with a role, and no way for an assessed organization to see its
own reports without being handed a key that could read everything.

## Decision

1. Accounts, users, sessions, invitations and access requests live in
   `hai_ops` (migration 0003). They are operational, not ontology, so the
   manifest is unchanged and no criterion or status code is involved.
2. Roles are a fixed table in `hai_core.accounts.ROLES`. Each role maps to a
   principal kind (admin, reviewer or user) and a default scope set. An
   inviter can narrow scopes and set industries; nothing beyond the role can
   be granted. Organization roles never carry review, signing or admin scopes.
3. A login issues a session row and an HS256 JWT that references it. Every
   request re-reads the session, user and account, so disabling a user or
   changing a role takes effect immediately while a reviewer still signs with a
   JWT (rule 6 holds). Admin-minted tokens and partner API keys keep working.
4. Visibility is a property of the principal (`org_ids`, `industries`) and
   is applied in `hai_core.visibility`: SQL filters for lists, a 404 for
   single resources, review tasks follow their assessment. API keys created
   by a console user belong to the user's account and inherit the restriction.
5. The platform sends no email. Invitation and password-reset links are
   shown once to the inviter. The first owner is created through
   `POST /v1/auth/bootstrap` or `hai-db create-owner` while no user exists.
6. Passwords use scrypt from the standard library, with a lockout after
   repeated failures. Tokens are stored as HMACs under the API key pepper.

## Consequences

* The console has sign-in and sign-up pages, a Team page for invitations and
  members, and Settings with profile, security and account-owned API keys.
* Participating organizations sign in with their work email and see only
  their reports; platform users can be scoped to industries they serve.
* Email delivery, single sign-on and self-service password reset by email
  are deliberate gaps; the data model does not prevent adding them.
