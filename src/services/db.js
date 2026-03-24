'use strict';

const { createClient } = require('@supabase/supabase-js');

const TABLE = 'hai_assessments';

// Initialise once — createClient is safe to call at module load time.
// SUPABASE_SERVICE_ROLE_KEY is used (not the anon key) so the backend
// can INSERT and SELECT without Row Level Security interference.
const supabase = createClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY
);

/**
 * Inserts one benchmark record into hai_assessments.
 *
 * @param {{ company_domain, industry, stage, size_band, score, confidence }} record
 * @returns {Promise<void>}
 * @throws {Error} if the insert fails
 */
async function insertBenchmark(record) {
    const { error } = await supabase
        .from(TABLE)
        .insert({
            company_domain: record.company_domain,
            industry:       record.industry,
            stage:          record.stage,
            size_band:      record.size_band,
            score:          record.score,
            confidence:     record.confidence
        });

    if (error) {
        throw new Error('DB insert failed: ' + error.message);
    }
}

/**
 * Computes the industry benchmark using only the most recent record
 * per company_domain — replicating the WordPress deduplication query exactly.
 *
 * SQL equivalent:
 *   SELECT AVG(t1.score), AVG(t1.confidence), COUNT(*)
 *   FROM hai_assessments t1
 *   INNER JOIN (
 *     SELECT MAX(created_at) AS max_date, company_domain
 *     FROM hai_assessments
 *     WHERE industry = $1
 *     GROUP BY company_domain
 *   ) t2
 *   ON  t1.company_domain = t2.company_domain
 *   AND t1.created_at     = t2.max_date
 *   WHERE t1.industry = $1
 *
 * The Supabase JS client does not support this join directly, so we
 * use rpc() with a Postgres function. The function definition to run
 * once in the Supabase SQL editor is documented in db-setup.sql.
 *
 * @param {string} industry
 * @returns {Promise<{ averageScore: number, averageConfidence: number, totalCompanies: number }>}
 * @throws {Error} if the query fails or returns no rows
 */
async function getIndustryAverage(industry) {
    const { data, error } = await supabase
        .rpc('get_industry_benchmark', { p_industry: industry });

    if (error) {
        throw new Error('DB benchmark query failed: ' + error.message);
    }

    // rpc returns an array; the function returns a single row
    const row = Array.isArray(data) ? data[0] : data;

    if (!row) {
        throw new Error('No benchmark data returned for industry: ' + industry);
    }

    return {
        averageScore:      Math.round(parseFloat(row.avg_score)      * 10) / 10,
        averageConfidence: Math.round(parseFloat(row.avg_confidence) * 10) / 10,
        totalCompanies:    parseInt(row.company_count, 10)
    };
}

module.exports = { insertBenchmark, getIndustryAverage };
