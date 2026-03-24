'use strict';

const { Router } = require('express');
const router = Router();

const { insertBenchmark, getIndustryAverage } = require('../services/db');

// POST /benchmark
//
// Accepts: application/x-www-form-urlencoded
//   domain, industry, stage, size, score, confidence
//
// Replicates WordPress action: record_hai_benchmark
//
// Process:
//   1. Validate required fields (domain, industry)
//   2. Insert record into hai_assessments
//   3. Query industry average (most recent record per domain only)
//   4. Return result
//
// Success:
//   { success: true, data: { industry, averageScore, averageConfidence, totalCompanies } }
//
// Failure:
//   { success: false, data: "error message" }

router.post('/', async (req, res) => {

    // ----------------------------------------------------------------
    // 1. Validate — matches WordPress required fields check exactly
    // ----------------------------------------------------------------
    const domain   = (req.body && req.body.domain   || '').trim();
    const industry = (req.body && req.body.industry || '').trim();

    if (!domain || !industry) {
        return res.status(200).json({
            success: false,
            data: 'Domain and Industry are required variables.'
        });
    }

    const stage    = (req.body.stage    || '').trim();
    const size     = (req.body.size     || '').trim();
    const score    = parseFloat(req.body.score)      || 0;
    const confidence = parseFloat(req.body.confidence) || 0;

    // ----------------------------------------------------------------
    // 2. Insert record
    // ----------------------------------------------------------------
    try {
        await insertBenchmark({
            company_domain: domain,
            industry,
            stage,
            size_band: size,
            score,
            confidence
        });
    } catch (err) {
        console.error('[benchmark] Insert failed:', err.message);
        return res.status(200).json({
            success: false,
            data: 'Failed to store benchmark record.'
        });
    }

    // ----------------------------------------------------------------
    // 3. Query industry average
    // ----------------------------------------------------------------
    let benchmarkResult;
    try {
        benchmarkResult = await getIndustryAverage(industry);
    } catch (err) {
        console.error('[benchmark] Average query failed:', err.message);
        return res.status(200).json({
            success: false,
            data: 'Failed to calculate benchmark.'
        });
    }

    // ----------------------------------------------------------------
    // 4. Return — shape matches WordPress wp_send_json_success exactly
    // ----------------------------------------------------------------
    return res.status(200).json({
        success: true,
        data: {
            industry,
            averageScore:      benchmarkResult.averageScore,
            averageConfidence: benchmarkResult.averageConfidence,
            totalCompanies:    benchmarkResult.totalCompanies
        }
    });
});

module.exports = router;
