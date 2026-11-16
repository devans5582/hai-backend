-- Keep finalized result views aligned with current assessment selection.
-- Review-pending results are visible in the application, not finalized benchmarks.
BEGIN;

CREATE OR REPLACE VIEW hai_ops.v_latest_results AS
SELECT DISTINCT ON (a.org_id)
    a.org_id, a.id AS assessment_id, a.stage_band, a.size_band, o.industry_code,
    r.hai_score, r.confidence_pct, r.outcome_status, r.created_at,
    a.ontology_version, a.methodology_version, a.ruleset_version
FROM hai.assessment_results r
JOIN hai.assessments a ON a.id = r.assessment_id
JOIN hai.organizations o ON o.id = a.org_id
WHERE NOT EXISTS (SELECT 1 FROM hai.assessment_results later WHERE later.supersedes_id = r.id)
  AND a.lifecycle_state IN ('completed', 'completed_unverified')
ORDER BY a.org_id, a.created_at DESC, a.id DESC, r.created_at DESC, r.id DESC;

CREATE OR REPLACE VIEW hai_ops.v_industry_benchmarks AS
SELECT industry_code AS industry, stage_band, size_band,
       count(*) AS organizations,
       round(avg(hai_score)::numeric, 1) AS average_score,
       round(avg(confidence_pct)::numeric, 1) AS average_confidence,
       ontology_version, methodology_version, ruleset_version
FROM hai_ops.v_latest_results
WHERE outcome_status <> 'access_limited' AND hai_score IS NOT NULL
GROUP BY industry_code, stage_band, size_band, ontology_version, methodology_version, ruleset_version;

COMMIT;
