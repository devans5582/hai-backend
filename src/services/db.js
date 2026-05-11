'use strict';

const { createClient } = require('@supabase/supabase-js');

const TABLE = 'hai_assessments';

// ── Node 18 / Supabase WebSocket fix ─────────────────────────────────────────
// @supabase/realtime-js throws a hard error on Node 18 when no native WebSocket
// is found.  This backend only uses the REST API (insertBenchmark, getIndustryAverage)
// and never opens Realtime subscriptions, so we:
//   1. Provide the `ws` package as the Realtime transport (silences the throw)
//   2. Set autoConnectSocket: false (prevents an unnecessary WS connection opening)
//
// `ws` is already in node_modules transitively; the explicit require here ensures
// it is resolved even if hoisting changes in a future npm update.
// ─────────────────────────────────────────────────────────────────────────────
let _ws;
try {
    _ws = require('ws');
} catch (_) {
    // ws not available — fall back to undefined; only fails on Node < 22 without ws
    _ws = undefined;
}

// Initialise once — createClient is safe to call at module load time.
// SUPABASE_SERVICE_ROLE_KEY is used (not the anon key) so the backend
// can INSERT and SELECT without Row Level Security interference.
const supabase = createClient(
    process.env.SUPABASE_URL,
    process.env.SUPABASE_SERVICE_ROLE_KEY,
    {
        realtime: {
            transport:         _ws,    // provide ws so Node 18 WebSocket factory doesn't throw
            autoConnectSocket: false,  // don't open a socket — this service only uses REST
            reconnectAfterMs:  () => 60000, // long back-off so retries don't spam logs if it does try
        }
    }
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
