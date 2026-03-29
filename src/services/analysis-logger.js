'use strict';

// ---------------------------------------------------------------
// analysis-logger.js  —  Phase 1
// Humaital HAI Platform — Analysis Log Service
//
// Single responsibility: insert ONE flat row into Supabase
// (hai_analysis_logs) after each evaluation completes.
//
// Design rules:
//   - Never throws to caller
//   - Non-blocking (caller does not await)
//   - No retries, no chaining, no side effects
//   - All fields are scalars — no nested JSON
//
// Required env vars:
//   SUPABASE_URL         e.g. https://xxxx.supabase.co
//   SUPABASE_SERVICE_KEY service-role key (not anon key)
// ---------------------------------------------------------------

const axios = require('axios');

// ── UUID v4 generator — no external dependency ───────────────────
function generateAnalysisId() {
    try {
        return require('crypto').randomUUID();
    } catch (_) {
        // Fallback for older Node versions
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
            const r = (Math.random() * 16) | 0;
            return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
        });
    }
}

// ── Supabase REST insert ─────────────────────────────────────────
async function insertLog(row) {
    const url = `${process.env.SUPABASE_URL}/rest/v1/hai_analysis_logs`;
    await axios.post(url, row, {
        timeout: 8000,
        headers: {
            'apikey':        process.env.SUPABASE_SERVICE_KEY,
            'Authorization': 'Bearer ' + process.env.SUPABASE_SERVICE_KEY,
            'Content-Type':  'application/json',
            'Prefer':        'return=minimal'
        },
        validateStatus: () => true   // never throw on HTTP error status
    });
}

// ── Scrape status helper ─────────────────────────────────────────
function deriveScrapeStatus(scrapeResult) {
    if (!scrapeResult || scrapeResult.scraper_blocked) return 'blocked';
    if (scrapeResult.partial_scrape)                   return 'partial';
    if (scrapeResult.limited_access)                   return 'limited';
    return 'ok';
}

// ── Main export ──────────────────────────────────────────────────

/**
 * writeLog — fire-and-forget. Caller must NOT await this.
 *
 * Usage in evaluate.js:
 *   writeLog({ analysisId, targetUrl, reqBody, scrapeResult, premiumReport }).catch(() => {});
 *
 * Fields that the backend cannot compute (final_score, confidence_score,
 * certification_status, benchmark_average, benchmark_position) are stored
 * as NULL. Phase 2 can add a PATCH endpoint to fill them from the frontend.
 */
async function writeLog({ analysisId, targetUrl, reqBody, scrapeResult, premiumReport }) {
    if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_KEY) {
        console.warn('[analysis-logger] Supabase env vars missing — log skipped');
        return;
    }

    try {
        // Signal profile — safe defaults when premiumReport is null
        const sp  = (premiumReport && premiumReport.signal_profile)  || {};
        const cal = (premiumReport && premiumReport.calibration)      || {};
        const ev  = (premiumReport && premiumReport.evidence_summary) || {};

        const row = {
            analysis_id:        analysisId,
            timestamp:          new Date().toISOString(),

            // Company metadata — from form body
            company_name:       (reqBody && reqBody.company)  || null,
            company_url:        targetUrl                      || null,
            industry:           (reqBody && reqBody.industry) || null,
            stage:              (reqBody && reqBody.stage)    || null,
            size:               (reqBody && reqBody.size)     || null,

            // Scrape outcome
            scrape_status:       deriveScrapeStatus(scrapeResult),
            limited_access_flag: !!(scrapeResult && scrapeResult.limited_access),

            // Evaluation state
            evaluation_state:   (premiumReport && premiumReport.evaluation_state) || 'unknown',

            // Signal counts
            high_signals:       typeof sp.high_signals   === 'number' ? sp.high_signals   : 0,
            medium_signals:     typeof sp.medium_signals === 'number' ? sp.medium_signals : 0,
            low_signals:        typeof sp.low_signals    === 'number' ? sp.low_signals    : 0,

            // Backend-computable scores (proxy values from calibration object)
            raw_score:          typeof cal.raw_score_proxy  === 'number' ? cal.raw_score_proxy  : null,
            calibrated_score:   typeof cal.calibrated_score === 'number' ? cal.calibrated_score : null,

            // Frontend-computed fields — NULL in Phase 1, filled by Phase 2 PATCH
            final_score:          null,
            evidence_strength:    ev.summary || null,
            confidence_score:     null,
            certification_status: null,
            benchmark_average:    null,
            benchmark_position:   null
        };

        await insertLog(row);
        console.log(`[analysis-logger] Log written — ${analysisId}`);

    } catch (err) {
        // Swallow all errors — logging must never affect the evaluation response
        console.error('[analysis-logger] writeLog failed (non-critical):', err.message);
    }
}

module.exports = { generateAnalysisId, writeLog };


// ═══════════════════════════════════════════════════════════════════
// TABLE DDL — run once in the Supabase SQL Editor
// ═══════════════════════════════════════════════════════════════════
//
// CREATE TABLE hai_analysis_logs (
//   id                   BIGSERIAL    PRIMARY KEY,
//   analysis_id          UUID         NOT NULL UNIQUE,
//   timestamp            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
//   company_name         TEXT,
//   company_url          TEXT,
//   industry             TEXT,
//   stage                TEXT,
//   size                 TEXT,
//   scrape_status        TEXT,        -- 'ok' | 'partial' | 'limited' | 'blocked'
//   limited_access_flag  BOOLEAN,
//   evaluation_state     TEXT,        -- 'valid' | 'partial_evaluation' | 'insufficient_evidence' | 'unknown'
//   high_signals         INTEGER,
//   medium_signals       INTEGER,
//   low_signals          INTEGER,
//   raw_score            NUMERIC(5,1),
//   calibrated_score     NUMERIC(5,1),
//   final_score          NUMERIC(5,1),   -- NULL in Phase 1
//   evidence_strength    TEXT,           -- NULL in Phase 1
//   confidence_score     INTEGER,        -- NULL in Phase 1
//   certification_status TEXT,           -- NULL in Phase 1
//   benchmark_average    NUMERIC(5,1),   -- NULL in Phase 1
//   benchmark_position   TEXT            -- NULL in Phase 1
// );
//
// CREATE INDEX ON hai_analysis_logs (timestamp DESC);
// CREATE INDEX ON hai_analysis_logs (analysis_id);
//
// -- RLS: service-role key bypasses automatically.
// -- Anon key has no access unless you explicitly grant it.
// ALTER TABLE hai_analysis_logs ENABLE ROW LEVEL SECURITY;
