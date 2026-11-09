-- User accounts for the console: the platform account (Humaital) and one account per
-- participating organization. Users sign in with email and password, hold a role with
-- explicit scopes and optional industries, and get revocable sessions. Invitations and
-- password resets are one-time tokens stored as HMACs. API keys gain an owning account so
-- a key created by an organization account is limited to that organization.
-- Never edited after it is applied; add a new numbered file instead.

CREATE TABLE hai_ops.accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL CHECK (kind IN ('platform', 'organization')),
    name text NOT NULL,
    org_id uuid UNIQUE REFERENCES hai.organizations(id),
    email_domain text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_accounts_org_link CHECK ((kind = 'organization') = (org_id IS NOT NULL))
);
-- Exactly one platform account.
CREATE UNIQUE INDEX uq_accounts_single_platform ON hai_ops.accounts ((kind)) WHERE kind = 'platform';

CREATE TABLE hai_ops.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES hai_ops.accounts(id),
    email text NOT NULL,
    name text NOT NULL,
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'reviewer', 'analyst', 'viewer', 'org_admin', 'org_member')),
    scopes text[] NOT NULL DEFAULT '{}',
    industries text[] NOT NULL DEFAULT '{}',
    password_hash text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    failed_logins integer NOT NULL DEFAULT 0,
    locked_until timestamptz,
    invited_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_login_at timestamptz
);
CREATE UNIQUE INDEX uq_users_email ON hai_ops.users (lower(email));
CREATE INDEX ix_users_account ON hai_ops.users (account_id);

CREATE TABLE hai_ops.sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES hai_ops.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz,
    revoked_at timestamptz,
    user_agent text
);
CREATE INDEX ix_sessions_user ON hai_ops.sessions (user_id, revoked_at);

CREATE TABLE hai_ops.invitations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL DEFAULT 'invite' CHECK (kind IN ('invite', 'password_reset')),
    account_id uuid NOT NULL REFERENCES hai_ops.accounts(id),
    user_id uuid REFERENCES hai_ops.users(id),
    email text NOT NULL,
    role text NOT NULL,
    scopes text[] NOT NULL DEFAULT '{}',
    industries text[] NOT NULL DEFAULT '{}',
    token_hmac text NOT NULL UNIQUE,
    invited_by text NOT NULL,
    invited_by_name text,
    message text,
    expires_at timestamptz NOT NULL,
    accepted_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_invitations_pending ON hai_ops.invitations (lower(email)) WHERE accepted_at IS NULL AND revoked_at IS NULL;

CREATE TABLE hai_ops.access_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    name text NOT NULL,
    organization_name text NOT NULL,
    website text,
    message text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'invited', 'dismissed')),
    resolved_by text,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_access_requests_pending ON hai_ops.access_requests (created_at) WHERE status = 'pending';

ALTER TABLE hai_ops.api_keys ADD COLUMN account_id uuid REFERENCES hai_ops.accounts(id);
CREATE INDEX ix_api_keys_account ON hai_ops.api_keys (account_id);

-- The API authenticates and manages accounts; the admin role seeds and repairs.
GRANT SELECT, INSERT, UPDATE ON hai_ops.accounts, hai_ops.users, hai_ops.sessions, hai_ops.invitations, hai_ops.access_requests
    TO hai_api, hai_admin;
-- Reviewer-role transactions read the acting user's own row (profile, sessions).
GRANT SELECT ON hai_ops.accounts, hai_ops.users, hai_ops.sessions TO hai_reviewer;
