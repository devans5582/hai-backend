'use strict';

// ── db.js — Supabase REST client (no WebSocket dependency) ───────────────────
//
// The @supabase/supabase-js SDK initialises a Realtime WebSocket client at
// startup even when you never use subscriptions.  On Node 18 this throws a
// hard error because native WebSocket is absent.  Rather than fight the SDK
// version or Node version, this module bypasses the JS client entirely and
// calls the Supabase REST + RPC APIs directly via axios — the same HTTP
// calls the SDK would make, with no WebSocket involvement whatsoever.
//
// Functions exposed are identical to the original:
//   insertBenchmark(record)     → POST /rest/v1/hai_assessments
//   getIndustryAverage(industry) → POST /rest/v1/rpc/get_industry_benchmark
// ─────────────────────────────────────────────────────────────────────────────

const axios = require('axios');

const TABLE = 'hai_assessments';

// Build Supabase REST headers once at module load.
// These are the same headers the JS SDK sends internally.
function supabaseHeaders() {
    return {
        'apikey':        process.env.SUPABASE_SERVICE_ROLE_KEY,
        'Authorization': 'Bearer ' + process.env.SUPABASE_SERVICE_ROLE_KEY,
        'Content-Type':  'application/json',
        'Prefer':        'return=minimal'
    };
}

function restUrl(path) {
    return process.env.SUPABASE_URL + '/rest/v1/' + path;
}

/**
 * Inserts one benchmark record into hai_assessments.
 *
 * @param {{ company_domain, industry, stage, size_band, score, confidence }} record
 * @returns {Promise<void>}
 * @throws {Error} if the insert fails
 */
async function insertBenchmark(record) {
    const resp = await axios.post(
        restUrl(TABLE),
        {
            company_domain:     record.company_domain,
            industry:           record.industry,
            stage:              record.stage,
            size_band:          record.size_band,
            score:              record.score,
            confidence:         record.confidence,
            // benchmark_eligible: false for access_limited runs — excluded from averages.
            // Defaults to true when not supplied (backwards-compatible with existing rows).
            benchmark_eligible: record.benchmark_eligible !== false
        },
        {
            headers:        supabaseHeaders(),
            validateStatus: () => true,
            timeout:        8000
        }
    );

    if (resp.status < 200 || resp.status >= 300) {
        throw new Error('DB insert failed: HTTP ' + resp.status + ' — ' + JSON.stringify(resp.data));
    }
}

/**
 * Computes the industry benchmark using only the most recent record
 * per company_domain — replicating the WordPress deduplication query exactly.
 *
 * Calls the get_industry_benchmark Postgres function via Supabase RPC.
 * The function definition is in db-setup.sql.
 *
 * @param {string} industry
 * @returns {Promise<{ averageScore: number, averageConfidence: number, totalCompanies: number }>}
 * @throws {Error} if the query fails or returns no rows
 */
async function getIndustryAverage(industry) {
    const resp = await axios.post(
        restUrl('rpc/get_industry_benchmark'),
        { p_industry: industry },
        {
            headers:        supabaseHeaders(),
            validateStatus: () => true,
            timeout:        8000
        }
    );

    if (resp.status < 200 || resp.status >= 300) {
        throw new Error('DB benchmark query failed: HTTP ' + resp.status + ' — ' + JSON.stringify(resp.data));
    }

    // RPC returns an array; the function returns a single row
    const row = Array.isArray(resp.data) ? resp.data[0] : resp.data;

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
