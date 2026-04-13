'use strict';

// ---------------------------------------------------------------
// analysis-logger.js  —  Phase 1 + Phase 2
// Humaital HAI Platform — Analysis Log Service
//
// Exports:
//   generateAnalysisId()              — UUID v4, called at /evaluate start
//   writeLog({ ... })                 — Phase 1: INSERT initial row (fire-and-forget)
//   patchLog(analysisId, fields)      — Phase 2: PATCH row with frontend-computed values
//
// Design rules:
//   - Never throws to caller
//   - writeLog is fire-and-forget (caller must not await)
//   - All fields are scalars — no nested JSON
//
// Required env vars:
//   SUPABASE_URL         e.g. https://xxxx.supabase.co
//   SUPABASE_SERVICE_KEY service-role key (not anon key)
// ---------------------------------------------------------------

const axios = require('axios');

// ── Shared Supabase headers ──────────────────────────────────────

function supabaseHeaders() {
    return {
        'apikey':        process.env.SUPABASE_SERVICE_KEY,
        'Authorization': 'Bearer ' + process.env.SUPABASE_SERVICE_KEY,
        'Content-Type':  'application/json',
        'Prefer':        'return=minimal'
    };
}

const TABLE_URL = () => `${process.env.SUPABASE_URL}/rest/v1/hai_analysis_logs`;

// ── UUID v4 generator — no external dependency ───────────────────

function generateAnalysisId() {
    try {
        return require('crypto').randomUUID();
    } catch (_) {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
            const r = (Math.random() * 16) | 0;
            return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
        });
    }
}

// ── Scrape status helper ─────────────────────────────────────────

function deriveScrapeStatus(scrapeResult) {
    if (!scrapeResult || scrapeResult.scraper_blocked) return 'blocked';
    if (scrapeResult.partial_scrape)                   return 'partial';
    if (scrapeResult.limited_access)                   return 'limited';
    return 'ok';
}

// ── Phase 1: INSERT initial log row ─────────────────────────────
//
// Called inside /evaluate immediately before the response is returned.
// Frontend-computed fields (final_score, confidence_score, etc.) are
// NULL at this point — filled by patchLog() in Phase 2.
//
// Caller must NOT await: writeLog(...).catch(() => {});

async function writeLog({ analysisId, targetUrl, reqBody, scrapeResult, premiumReport }) {
    if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_KEY) {
        console.warn('[analysis-logger] Supabase env vars missing — log skipped');
        return;
    }

    try {
        const sp  = (premiumReport && premiumReport.signal_profile)  || {};
        const cal = (premiumReport && premiumReport.calibration)      || {};
        const ev  = (premiumReport && premiumReport.evidence_summary) || {};

        const row = {
            analysis_id:        analysisId,
            timestamp:          new Date().toISOString(),

            // Company metadata from form body
            // company_name comes from the frontend form, not req.body in /evaluate.
            // It is patched in Phase 2 along with industry/stage/size when those
            // fields are not present in the original request body.
            company_name:        (reqBody && reqBody.company)  || null,
            company_url:         targetUrl                      || null,
            industry:            (reqBody && reqBody.industry) || null,
            stage:               (reqBody && reqBody.stage)    || null,
            size:                (reqBody && reqBody.size)     || null,

            // Scrape outcome
            scrape_status:       deriveScrapeStatus(scrapeResult),
            limited_access_flag: !!(scrapeResult && scrapeResult.limited_access),

            // Evaluation state
            evaluation_state:    (premiumReport && premiumReport.evaluation_state) || 'unknown',

            // Signal counts
            high_signals:        typeof sp.high_signals   === 'number' ? sp.high_signals   : 0,
            medium_signals:      typeof sp.medium_signals === 'number' ? sp.medium_signals : 0,
            low_signals:         typeof sp.low_signals    === 'number' ? sp.low_signals    : 0,

            // Backend-computable score proxies from calibration object
            raw_score:           typeof cal.raw_score_proxy  === 'number' ? cal.raw_score_proxy  : null,
            calibrated_score:    typeof cal.calibrated_score === 'number' ? cal.calibrated_score : null,

            // Phase 2 fields — NULL until patchLog() is called by frontend
            final_score:          null,
            evidence_strength:    ev.summary || null,
            confidence_score:     null,
            certification_status: null,
            benchmark_average:    null,
            benchmark_position:   null,
            pdf_generated_status: null,
            email_delivery_status: null
        };

        await axios.post(TABLE_URL(), row, {
            timeout: 8000,
            headers: supabaseHeaders(),
            validateStatus: () => true
        });
        console.log(`[analysis-logger] Log written — ${analysisId}`);

    } catch (err) {
        console.error('[analysis-logger] writeLog failed (non-critical):', err.message);
    }
}

// ── Phase 2: PATCH log row with frontend-computed values ─────────
//
// Called by PATCH /log/:analysisId (routes/log-patch.js).
// Matches the row by analysis_id and updates only the supplied fields.
// Returns { ok: true } on success, { ok: false } on any failure.
// Never throws.

async function patchLog(analysisId, fields) {
    if (!process.env.SUPABASE_URL || !process.env.SUPABASE_SERVICE_KEY) {
        console.warn('[analysis-logger] Supabase env vars missing — patch skipped');
        return { ok: false };
    }

    try {
        // ── Build sanitized payload ──────────────────────────────────────────
        // Only scalar values for explicitly allowed columns are sent.
        // Nested objects/arrays and undefined values are dropped to
        // prevent Supabase returning HTTP 400 on unrecognised columns
        // or non-scalar values.
        const ALLOWED_PATCH_FIELDS = [
            'company_name',
            'industry',
            'stage',
            'size',
            'final_score',
            'evidence_strength',
            'confidence_score',
            'certification_status',
            'benchmark_average',
            'benchmark_position',
            'pdf_generated_status',
            'email_delivery_status'
        ];

        const sanitizedFields = {};
        for (const key of ALLOWED_PATCH_FIELDS) {
            if (!(key in fields)) continue;           // key absent — skip
            const val = fields[key];
            if (val === undefined) continue;          // undefined — skip
            if (val !== null && typeof val === 'object') continue; // object/array — skip
            sanitizedFields[key] = val;               // null | string | number | boolean — keep
        }

        const url = TABLE_URL() + `?analysis_id=eq.${encodeURIComponent(analysisId)}`;

        console.log(`[analysis-logger] PATCH URL — ${url}`);
        console.log(`[analysis-logger] PATCH payload — ${JSON.stringify(sanitizedFields)}`);

        const resp = await axios.patch(url, sanitizedFields, {
            timeout: 8000,
            headers: supabaseHeaders(),
            validateStatus: () => true
        });

        if (resp.status >= 200 && resp.status < 300) {
            console.log(`[analysis-logger] Patch OK — ${analysisId}`);
            return { ok: true };
        }

        console.warn(`[analysis-logger] Patch HTTP ${resp.status} — ${analysisId} — ${JSON.stringify(resp.data)}`);
        return { ok: false };

    } catch (err) {
        console.error('[analysis-logger] patchLog failed:', err.message);
        return { ok: false };
    }
}

module.exports = { generateAnalysisId, writeLog, patchLog };


// ═══════════════════════════════════════════════════════════════════
// TABLE DDL — run once in Supabase SQL Editor
// Phase 2 adds pdf_generated_status and email_delivery_status columns.
// If upgrading from Phase 1, run the two ALTER TABLE lines only.
// ═══════════════════════════════════════════════════════════════════
//
// -- Full schema (fresh install):
//
// CREATE TABLE hai_analysis_logs (
//   id                    BIGSERIAL    PRIMARY KEY,
//   analysis_id           UUID         NOT NULL UNIQUE,
//   timestamp             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
//   company_name          TEXT,
//   company_url           TEXT,
//   industry              TEXT,
//   stage                 TEXT,
//   size                  TEXT,
//   scrape_status         TEXT,         -- 'ok' | 'partial' | 'limited' | 'blocked'
//   limited_access_flag   BOOLEAN,
//   evaluation_state      TEXT,         -- 'valid' | 'partial_evaluation' | 'insufficient_evidence' | 'unknown'
//   high_signals          INTEGER,
//   medium_signals        INTEGER,
//   low_signals           INTEGER,
//   raw_score             NUMERIC(5,1),
//   calibrated_score      NUMERIC(5,1),
//   final_score           NUMERIC(5,1),  -- from Phase 2 PATCH
//   evidence_strength     TEXT,          -- from Phase 2 PATCH
//   confidence_score      INTEGER,       -- from Phase 2 PATCH
//   certification_status  TEXT,          -- from Phase 2 PATCH
//   benchmark_average     NUMERIC(5,1),  -- from Phase 2 PATCH
//   benchmark_position    TEXT,          -- from Phase 2 PATCH
//   pdf_generated_status  BOOLEAN,       -- from Phase 2 PATCH (new in Phase 2)
//   email_delivery_status BOOLEAN        -- from Phase 2 PATCH (new in Phase 2)
// );
//
// CREATE INDEX ON hai_analysis_logs (timestamp DESC);
// CREATE INDEX ON hai_analysis_logs (analysis_id);
//
// ALTER TABLE hai_analysis_logs ENABLE ROW LEVEL SECURITY;
//
// -- Upgrading from Phase 1 only (skip if fresh install):
// ALTER TABLE hai_analysis_logs ADD COLUMN pdf_generated_status  BOOLEAN;
// ALTER TABLE hai_analysis_logs ADD COLUMN email_delivery_status BOOLEAN;
