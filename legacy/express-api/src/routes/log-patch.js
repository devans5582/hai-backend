'use strict';

// ---------------------------------------------------------------
// log-patch.js  —  PATCH /log/:analysisId
//
// Receives frontend-computed values after the full assessment
// cycle completes and patches the Phase 1 log row in Supabase.
//
// Called by main.js / bundle.js after:
//   - verifiedScore and confPercent are finalized
//   - benchmark fetch returns industry average
//   - PDF is generated (or fails)
//   - Email is sent (or fails)
//
// Phase 4 additions:
//   - edgar_signals, wayback_signals, oecd_signals,
//     github_signals, academic_signals, supplementary_total
//
// Accepted fields (all optional — only present fields are patched):
//   company_name, industry, stage, size
//   final_score, confidence_score, certification_status
//   evidence_strength, benchmark_average, benchmark_position
//   pdf_generated_status, email_delivery_status
//   edgar_signals, wayback_signals, oecd_signals,
//   github_signals, academic_signals, supplementary_total
//
// Returns:
//   { success: true }   on success
//   { success: false }  on failure (non-fatal — frontend ignores)
// ---------------------------------------------------------------

const { Router }   = require('express');
const { patchLog } = require('../services/analysis-logger');

const router = Router();

// Allowed patch fields — whitelist prevents arbitrary column injection.
// Phase 4 supplementary signal columns added at the bottom.
const ALLOWED_FIELDS = new Set([
    // Company metadata (may be absent from Phase 1 row if not in evaluate body)
    'company_name',
    'industry',
    'stage',
    'size',

    // Frontend-computed scores
    'final_score',
    'confidence_score',
    'certification_status',
    'evidence_strength',

    // Benchmark
    'benchmark_average',
    'benchmark_position',

    // Delivery status
    'pdf_generated_status',
    'email_delivery_status',

    // Phase 4 — supplementary evidence signal counts
    'edgar_signals',
    'wayback_signals',
    'oecd_signals',
    'github_signals',
    'academic_signals',
    'supplementary_total',
]);

// Fields that should be stored as numbers rather than strings
const NUMERIC_FIELDS = new Set([
    'final_score',
    'confidence_score',
    'benchmark_average',
    'edgar_signals',
    'wayback_signals',
    'oecd_signals',
    'github_signals',
    'academic_signals',
    'supplementary_total',
]);

// Fields that should be stored as booleans
const BOOLEAN_FIELDS = new Set([
    'pdf_generated_status',
    'email_delivery_status',
]);

// PATCH /log/:analysisId
router.patch('/:analysisId', async (req, res) => {
    const { analysisId } = req.params;

    if (!analysisId || !analysisId.trim()) {
        return res.status(200).json({ success: false, data: 'Missing analysisId.' });
    }

    // Build the fields object from whitelisted body keys only
    const fields = {};
    const body   = req.body || {};

    for (const key of ALLOWED_FIELDS) {
        if (body[key] === undefined || body[key] === null || body[key] === '') continue;

        let value = body[key];

        if (NUMERIC_FIELDS.has(key)) {
            const num = parseFloat(value);
            if (!isNaN(num)) fields[key] = num;
        } else if (BOOLEAN_FIELDS.has(key)) {
            // Accept 'true'/'false' strings from URLSearchParams as well as real booleans
            if (value === 'true'  || value === true)  fields[key] = true;
            if (value === 'false' || value === false) fields[key] = false;
        } else {
            fields[key] = String(value).trim().slice(0, 500); // safety length cap
        }
    }

    if (Object.keys(fields).length === 0) {
        // Nothing to patch — still a success from the caller's perspective
        return res.status(200).json({ success: true, data: 'No fields to update.' });
    }

    const result = await patchLog(analysisId.trim(), fields);

    return res.status(200).json({
        success: result.ok,
        data:    result.ok ? 'Log updated.' : 'Log update failed (non-critical).'
    });
});

module.exports = router;
