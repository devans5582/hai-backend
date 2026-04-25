'use strict';

// src/routes/evaluate.js
// POST /evaluate — main evaluation endpoint
// Phase 6: entity resolution (Step 0) + Phase 4 supplementary evidence

const express               = require('express');
const router                = express.Router();
const { v4: uuidv4 }        = require('uuid');

const scraper               = require('../services/scraper');
const { callOpenAI }        = require('../services/openai');
const { generatePremiumReport } = require('../services/report-generator');
const { fetchSupplementaryEvidence } = require('../services/supplementary-evidence');
const { writeLog }          = require('../services/analysis-logger');
const { resolveEntity }     = require('../services/entity-resolver');

// ── Input validation helper ─────────────────────────────────────────────────
function isValidUrl(str) {
    try {
        const u = new URL(str.startsWith('http') ? str : 'https://' + str);
        return u.hostname.includes('.');
    } catch {
        return false;
    }
}

function normaliseUrl(str) {
    if (!str) return null;
    const s = str.trim();
    return s.startsWith('http') ? s : 'https://' + s;
}

// ── Route handler ───────────────────────────────────────────────────────────
router.post('/', async (req, res) => {
    const startTime = Date.now();

    // ── Parse and validate inputs ──────────────────────────────────────────
    const rawUrl    = (req.body.url     || '').trim();
    const company   = (req.body.company || '').trim();
    const industry  = (req.body.industry || 'Technology').trim();
    const stage     = (req.body.stage   || 'startup').trim();
    const size      = (req.body.size    || '1-10').trim();

    if (!rawUrl) {
        return res.status(400).json({ success: false, error: 'URL is required.' });
    }
    if (!isValidUrl(rawUrl)) {
        return res.status(400).json({ success: false, error: 'Invalid URL provided.' });
    }
    if (!company) {
        return res.status(400).json({ success: false, error: 'Company name is required.' });
    }

    const url = normaliseUrl(rawUrl);
    const analysisId = uuidv4();

    console.log(`[HAI /evaluate] id=${analysisId} company="${company}" url=${url} industry=${industry} stage=${stage} size=${size}`);

    try {

        // ── Step 0: Entity resolution (Phase 6) ───────────────────────────
        // Runs before the scraper. Determines the canonical company name and
        // CIK used for all downstream evidence queries.
        // Non-blocking — if resolution fails entirely the assessment continues
        // with the submitted name and URL.
        let entityProfile = null;
        let queryName     = company;  // default: use submitted name

        try {
            entityProfile = await resolveEntity(company, url);
            queryName     = entityProfile.resolvedName;
            console.log(`[HAI] Entity resolved: "${queryName}" | confidence=${entityProfile.overallConfidence.toFixed(2)} | public=${entityProfile.isPublicCompany} | warnings=${entityProfile.warnings.length}`);
        } catch (entityErr) {
            console.warn('[HAI] Entity resolution failed (non-blocking):', entityErr.message);
            entityProfile = {
                inputName:    company,
                inputUrl:     url,
                resolvedName: company,
                resolvedDomain: null,
                wikidataId:   null,
                lei:          null,
                cik:          null,
                isPublicCompany: false,
                resolvedIndustry: null,
                nameMatchScore: 0,
                domainVerified: null,
                domainMatchConfidence: 0,
                edgarCrossCheckFound: false,
                overallConfidence: 0,
                warnings: ['Entity resolution unavailable — assessment uses submitted name and URL.'],
                wikidataIsOneSignal: true,
                resolvedAt: new Date().toISOString()
            };
        }

        // ── Step 1: Scrape website ─────────────────────────────────────────
        console.log(`[HAI] Scraping: ${url}`);
        const scrapeResult = await scraper.scrape(url);
        const {
            combined_text    = '',
            scraped_pages    = [],
            scrape_status    = 'blocked',
            limited_access   = false,
            partial_scrape   = false
        } = scrapeResult;

        console.log(`[HAI] Scrape status=${scrape_status} pages=${scraped_pages.length} chars=${combined_text.length}`);

        // ── Step 2: Supplementary evidence (Phase 4+6) ────────────────────
        // Triggered when scrape is partial or limited.
        // Uses queryName (entity-resolved) for more accurate evidence queries.
        let supplementarySignals = null;

        if (partial_scrape || limited_access || scrape_status === 'partial' || scrape_status === 'limited') {
            console.log('[HAI] Triggering supplementary evidence fetch...');
            try {
                supplementarySignals = await fetchSupplementaryEvidence(
                    queryName,
                    url,
                    industry,
                    { entityProfile, combinedText: combined_text }
                );
                const sc = supplementarySignals;
                console.log(`[HAI] Supplementary: edgar=${sc.edgarSignals} oecd=${sc.oecdSignals} academic=${sc.academicSignals} github=${sc.githubSignals} wayback=${sc.waybackSignals} total=${sc.totalSignals}`);
                if (sc.impact && sc.impact.negativeOverrides && sc.impact.negativeOverrides.length > 0) {
                    console.log(`[HAI] Negative overrides applied: ${sc.impact.negativeOverrides.length} criteria affected. Worst severity: ${sc.impact.worstSeverity}`);
                }
            } catch (suppErr) {
                console.warn('[HAI] Supplementary evidence fetch failed (non-blocking):', suppErr.message);
                supplementarySignals = null;
            }
        }

        // ── Step 3: Guard — OpenAI API key ────────────────────────────────
        if (!process.env.OPENAI_API_KEY) {
            console.error('[HAI] OPENAI_API_KEY is not set');
            return res.status(500).json({ success: false, error: 'Evaluation service is not configured. Please contact support.' });
        }

        // ── Step 4: OpenAI rubric evaluation ──────────────────────────────
        console.log('[HAI] Calling OpenAI for rubric evaluation...');
        let evaluation = null;
        try {
            evaluation = await callOpenAI(combined_text, company, industry);
            console.log('[HAI] OpenAI evaluation complete. Criteria evaluated:', Object.keys(evaluation || {}).length);
        } catch (aiErr) {
            console.error('[HAI] OpenAI evaluation failed:', aiErr.message);
            return res.status(500).json({ success: false, error: 'Evaluation could not be completed. Please try again.' });
        }

        // ── Step 5: Premium report generation ─────────────────────────────
        console.log('[HAI] Generating premium report...');
        let premiumReport    = null;
        let evaluationState  = 'valid';
        let calibration      = null;

        try {
            const reportResult = await generatePremiumReport(
                evaluation,
                combined_text,
                supplementarySignals,
                company,
                industry,
                stage,
                size
            );
            premiumReport   = reportResult.premiumReport   || null;
            evaluationState = reportResult.evaluationState || 'valid';
            calibration     = reportResult.calibration     || null;
            console.log(`[HAI] Premium report: state=${evaluationState}`);
        } catch (reportErr) {
            console.warn('[HAI] Premium report generation failed (non-blocking):', reportErr.message);
            evaluationState = 'valid';
        }

        // ── Step 6: Phase 1 log (fire-and-forget) ─────────────────────────
        const logPayload = {
            analysis_id:          analysisId,
            company_name:         company,
            company_url:          url,
            industry,
            stage,
            size,
            scrape_status,
            limited_access_flag:  limited_access || false,
            evaluation_state:     evaluationState,
            // Supplementary signal counts for logging
            edgar_signals:        supplementarySignals?.edgarSignals    ?? 0,
            wayback_signals:      supplementarySignals?.waybackSignals  ?? 0,
            oecd_signals:         supplementarySignals?.oecdSignals     ?? 0,
            github_signals:       supplementarySignals?.githubSignals   ?? 0,
            academic_signals:     supplementarySignals?.academicSignals ?? 0,
            supplementary_total:  supplementarySignals?.totalSignals    ?? 0,
            // Phase 6: entity resolution fields
            entity_resolved_name: entityProfile?.resolvedName          ?? '',
            entity_wikidata_id:   entityProfile?.wikidataId            ?? '',
            entity_is_public:     entityProfile?.isPublicCompany       ?? false,
            entity_confidence:    entityProfile?.overallConfidence      ?? 0,
            entity_domain_match:  entityProfile?.domainVerified        ?? null,
            // Phase 6: override fields
            has_overrides:        supplementarySignals?.impact?.hasOverrides    ?? false,
            override_count:       supplementarySignals?.impact?.negativeOverrides?.length ?? 0,
            worst_override:       supplementarySignals?.impact?.worstSeverity   ?? '',
            // Phase 6: freshness
            avg_evidence_freshness: supplementarySignals?.impact?.avgFreshness  ?? null,
            // Phase 6: execution
            execution_gap_count:    supplementarySignals?.impact?.executionGapCount    ?? 0,
            verified_execution_count: supplementarySignals?.impact?.verifiedExecutionCount ?? 0,
        };

        writeLog(logPayload).catch(logErr =>
            console.warn('[HAI] Phase 1 log write failed (non-blocking):', logErr.message)
        );

        // ── Step 7: Build and return response ─────────────────────────────
        const elapsed = Date.now() - startTime;
        console.log(`[HAI /evaluate] Complete in ${elapsed}ms`);

        return res.json({
            success:               true,
            analysis_id:           analysisId,
            evaluation:            evaluation        || {},
            scraped_pages:         scraped_pages,
            limited_access:        limited_access    || false,
            partial_scrape:        partial_scrape    || false,
            premiumReport:         premiumReport,
            evaluation_state:      evaluationState,
            calibration:           calibration,
            supplementary_signals: supplementarySignals,
            // Phase 6: entity profile returned to frontend for entity card display
            entityProfile:         entityProfile,
        });

    } catch (err) {
        console.error('[HAI /evaluate] Unhandled error:', err);
        return res.status(500).json({
            success: false,
            error:   'An unexpected error occurred. Please try again.',
        });
    }
});

module.exports = router;
