'use strict';

// ---------------------------------------------------------------
// routes/log-patch.js
// Railway route: PATCH /log/:analysisId
//
// Called by bundle.js (simulateEmailSend) after:
//   - final score is computed
//   - confidence is computed
//   - certification status is determined
//   - benchmark result is returned (or timed out)
//   - PDF generation result is known
//   - email dispatch result is known
//
// Security:
//   The analysis_id is a UUID v4 — opaque and not guessable.
//   It acts as the write token for this specific log row.
//   Only the fields in the ALLOWED_FIELDS whitelist can be updated.
//   No auth header is required from the browser (avoids exposing
//   any secret in frontend JS). The writable fields contain no
//   secrets — only computed scores and delivery status.
// ---------------------------------------------------------------

const { Router }   = require('express');
const { patchLog } = require('../services/analysis-logger');

const router = Router({ mergeParams: true });

// UUID v4 pattern — rejects anything that isn't a valid v4 UUID
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

// Whitelist of patchable fields.
// Any key sent by the frontend that is not in this set is silently dropped.
const ALLOWED_FIELDS = new Set([
    'company_name',
    'industry',
    'stage',
    'size',
    'final_score',
    'confidence_score',
    'certification_status',
    'benchmark_average',
    'benchmark_position',
    'pdf_generated_status',
    'email_delivery_status',
    'evidence_strength'
]);

router.patch('/:analysisId', async (req, res) => {
    const { analysisId } = req.params;

    // Validate UUID format
    if (!analysisId || !UUID_RE.test(analysisId)) {
        return res.status(400).json({ success: false, data: 'Invalid analysis_id format.' });
    }

    const body = req.body || {};

    // Build patch object — only whitelisted fields, with type coercion
    const patch = {};

    if (ALLOWED_FIELDS.has('company_name')      && body.company_name      != null) patch.company_name      = String(body.company_name).slice(0, 255);
    if (ALLOWED_FIELDS.has('industry')          && body.industry          != null) patch.industry          = String(body.industry).slice(0, 100);
    if (ALLOWED_FIELDS.has('stage')             && body.stage             != null) patch.stage             = String(body.stage).slice(0, 100);
    if (ALLOWED_FIELDS.has('size')              && body.size              != null) patch.size              = String(body.size).slice(0, 100);
    if (ALLOWED_FIELDS.has('evidence_strength') && body.evidence_strength != null) patch.evidence_strength = String(body.evidence_strength).slice(0, 50);
    if (ALLOWED_FIELDS.has('certification_status') && body.certification_status != null) patch.certification_status = String(body.certification_status).slice(0, 100);
    if (ALLOWED_FIELDS.has('benchmark_position')   && body.benchmark_position   != null) patch.benchmark_position   = String(body.benchmark_position).slice(0, 20);

    // Numeric fields — only set if parseable
    if (ALLOWED_FIELDS.has('final_score') && body.final_score != null) {
        const n = parseFloat(body.final_score);
        if (!isNaN(n)) patch.final_score = Math.round(n * 10) / 10;
    }
    if (ALLOWED_FIELDS.has('confidence_score') && body.confidence_score != null) {
        const n = parseInt(body.confidence_score, 10);
        if (!isNaN(n)) patch.confidence_score = n;
    }
    if (ALLOWED_FIELDS.has('benchmark_average') && body.benchmark_average != null) {
        const n = parseFloat(body.benchmark_average);
        if (!isNaN(n)) patch.benchmark_average = Math.round(n * 10) / 10;
    }

    // Boolean fields — accept 'true'/'false' strings from form-encoded body
    if (ALLOWED_FIELDS.has('pdf_generated_status') && body.pdf_generated_status != null) {
        patch.pdf_generated_status = (body.pdf_generated_status === true || body.pdf_generated_status === 'true');
    }
    if (ALLOWED_FIELDS.has('email_delivery_status') && body.email_delivery_status != null) {
        patch.email_delivery_status = (body.email_delivery_status === true || body.email_delivery_status === 'true');
    }

    if (Object.keys(patch).length === 0) {
        return res.status(400).json({ success: false, data: 'No valid fields supplied.' });
    }

    const result = await patchLog(analysisId, patch);

    // Always return 200 — a patch failure is non-critical and must not
    // surface as an error to the frontend or affect UX in any way.
    return res.status(200).json({ success: result.ok });
});

module.exports = router;
