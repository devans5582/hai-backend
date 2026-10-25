-- Hand-written operational schema and cross-table integrity.
-- Applied after the generated baseline. Never edited after it is applied; add
-- a new numbered file instead (the checksum ledger refuses edits).

-- --------------------------------------------------------------------------
-- hai_ops: tables that are not part of the domain ontology
-- --------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS hai_ops;
GRANT USAGE ON SCHEMA hai_ops TO hai_pipeline, hai_engine, hai_reviewer, hai_api, hai_admin;

-- Job queue
CREATE TABLE hai_ops.jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    priority integer NOT NULL DEFAULT 0,
    dedupe_key text,
    state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'running', 'done', 'failed', 'dead')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    run_after timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    locked_by text,
    last_error text,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE UNIQUE INDEX uq_jobs_active_dedupe ON hai_ops.jobs (dedupe_key) WHERE state IN ('queued', 'running');
CREATE INDEX ix_jobs_claim ON hai_ops.jobs (state, run_after, priority DESC);
GRANT SELECT, INSERT, UPDATE ON hai_ops.jobs TO hai_pipeline, hai_engine, hai_api, hai_admin, hai_reviewer;

-- API keys: only an HMAC of the secret is stored
CREATE TABLE hai_ops.api_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key_id text NOT NULL UNIQUE,
    name text NOT NULL,
    key_hmac text NOT NULL,
    scopes text[] NOT NULL DEFAULT '{}',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    last_used_at timestamptz
);
GRANT SELECT, UPDATE ON hai_ops.api_keys TO hai_api;
GRANT SELECT, INSERT, UPDATE ON hai_ops.api_keys TO hai_admin;

-- Webhooks
CREATE TABLE hai_ops.webhook_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner text NOT NULL,
    url text NOT NULL,
    secret text NOT NULL,
    events text[] NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE hai_ops.webhook_deliveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id uuid NOT NULL REFERENCES hai_ops.webhook_subscriptions(id),
    event text NOT NULL,
    payload jsonb NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    delivered_at timestamptz,
    last_status integer,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON hai_ops.webhook_subscriptions, hai_ops.webhook_deliveries
    TO hai_api, hai_engine, hai_pipeline, hai_reviewer, hai_admin;

-- Review queue tasks (the reviewable rows live in hai.*; tasks track the queue)
CREATE TABLE hai_ops.review_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id uuid REFERENCES hai.assessments(id),
    subject_type hai.review_subject_type NOT NULL,
    subject_id uuid NOT NULL,
    reason text NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'escalated', 'closed')),
    opened_by text NOT NULL,
    excluded_reviewers text[] NOT NULL DEFAULT '{}',
    closed_by text,
    closed_at timestamptz,
    closing_review_id uuid REFERENCES hai.reviews(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_review_tasks_open ON hai_ops.review_tasks (status, created_at);
GRANT SELECT, INSERT, UPDATE ON hai_ops.review_tasks TO hai_engine, hai_reviewer, hai_api, hai_pipeline, hai_admin;

-- Continuous monitoring subscriptions (beyond v1 extension point)
CREATE TABLE hai_ops.monitoring_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES hai.organizations(id),
    interval_days integer NOT NULL DEFAULT 90 CHECK (interval_days >= 1),
    active boolean NOT NULL DEFAULT true,
    requested_by text NOT NULL,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    last_assessment_id uuid REFERENCES hai.assessments(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON hai_ops.monitoring_subscriptions TO hai_api, hai_engine, hai_pipeline, hai_admin;

-- Evidence portal uploads (enter the pipeline as claims through the UPLOAD connector)
CREATE TABLE hai_ops.uploads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES hai.organizations(id),
    filename text NOT NULL,
    content_type text NOT NULL,
    sha256 text NOT NULL,
    blob_uri text NOT NULL,
    assertion_text text NOT NULL,
    claim_scope hai.claim_scope_type NOT NULL DEFAULT 'organization',
    submitted_by text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ingested', 'rejected')),
    source_document_id uuid REFERENCES hai.source_documents(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON hai_ops.uploads TO hai_api, hai_pipeline, hai_admin;

-- Methodology seeding replaces applicability rows per criterion
GRANT DELETE ON hai.criterion_applicability TO hai_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA hai_ops TO hai_admin;

-- --------------------------------------------------------------------------
-- IC-13: hai_certified requires a signed certification decision (constraint trigger)
-- --------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION hai.trgfn_results_require_certification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.outcome_status = 'hai_certified' AND NOT EXISTS (
        SELECT 1 FROM hai.certification_decisions cd
        WHERE cd.assessment_id = NEW.assessment_id
          AND cd.decision = 'certified'
          AND cd.reviewer_id IS NOT NULL
          AND cd.signed_at IS NOT NULL
          AND cd.supersedes_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM hai.certification_decisions later WHERE later.supersedes_id = cd.id)
    ) THEN
        RAISE EXCEPTION 'HAI_CERTIFICATION: hai_certified requires a signed certification decision (IC-13)'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER trg_results_require_certification
    AFTER INSERT ON hai.assessment_results
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW EXECUTE FUNCTION hai.trgfn_results_require_certification();

-- --------------------------------------------------------------------------
-- IC-12: row-level security on decision-bearing tables, in addition to grants.
-- Writes are allowed only to the owning component role (or the table owner).
-- --------------------------------------------------------------------------
ALTER TABLE hai.criterion_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE hai.assessment_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE hai.certification_decisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY read_all ON hai.criterion_decisions FOR SELECT USING (true);
CREATE POLICY read_all ON hai.assessment_results FOR SELECT USING (true);
CREATE POLICY read_all ON hai.certification_decisions FOR SELECT USING (true);
CREATE POLICY engine_writes ON hai.criterion_decisions FOR INSERT TO hai_engine WITH CHECK (true);
CREATE POLICY engine_writes ON hai.assessment_results FOR INSERT TO hai_engine WITH CHECK (true);
CREATE POLICY reviewer_writes ON hai.certification_decisions FOR INSERT TO hai_reviewer WITH CHECK (true);

-- --------------------------------------------------------------------------
-- Peer benchmarks: latest result per organization, excluding access-limited runs
-- --------------------------------------------------------------------------
CREATE OR REPLACE VIEW hai_ops.v_latest_results AS
SELECT DISTINCT ON (a.org_id)
    a.org_id, a.id AS assessment_id, a.stage_band, a.size_band, o.industry_code,
    r.hai_score, r.confidence_pct, r.outcome_status, r.created_at
FROM hai.assessment_results r
JOIN hai.assessments a ON a.id = r.assessment_id
JOIN hai.organizations o ON o.id = a.org_id
WHERE r.supersedes_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM hai.assessment_results later WHERE later.supersedes_id = r.id)
  AND a.lifecycle_state IN ('completed', 'completed_unverified')
ORDER BY a.org_id, r.created_at DESC;

CREATE OR REPLACE VIEW hai_ops.v_industry_benchmarks AS
SELECT industry_code AS industry, stage_band, size_band,
       count(*) AS organizations,
       round(avg(hai_score)::numeric, 1) AS average_score,
       round(avg(confidence_pct)::numeric, 1) AS average_confidence
FROM hai_ops.v_latest_results
WHERE outcome_status <> 'access_limited' AND hai_score IS NOT NULL
GROUP BY industry_code, stage_band, size_band;
GRANT SELECT ON hai_ops.v_latest_results, hai_ops.v_industry_benchmarks
    TO hai_pipeline, hai_engine, hai_reviewer, hai_api, hai_admin;
