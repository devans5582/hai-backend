'use strict';

// src/routes/evaluate.js
// POST /evaluate — main evaluation endpoint
// Phase 6: entity resolution (Step 0) + Phase 4 supplementary evidence

const express               = require('express');
const router                = express.Router();
const { v4: uuidv4 }        = require('uuid');

// ── Service imports with defensive handling ────────────────────────────────
// Each service may export differently — handle both patterns safely.
const scraperModule         = require('../services/scraper');
const openaiModule          = require('../services/openai');
const reportModule          = require('../services/report-generator');
const suppModule            = require('../services/supplementary-evidence');
const loggerModule          = require('../services/analysis-logger');
const entityModule          = require('../services/entity-resolver');

// Resolve the actual functions regardless of export pattern
// Pattern A: module.exports = { scrape: async fn }  → scraperModule.scrape
// Pattern B: module.exports = async fn              → scraperModule directly
const scrape            = typeof scraperModule.scrape === 'function'
                            ? scraperModule.scrape.bind(scraperModule)
                            : typeof scraperModule === 'function'
                                ? scraperModule
                                : null;

const callOpenAI        = typeof openaiModule.callOpenAI === 'function'
                            ? openaiModule.callOpenAI.bind(openaiModule)
                            : typeof openaiModule === 'function'
                                ? openaiModule
                                : null;

const generatePremiumReport = typeof reportModule.generatePremiumReport === 'function'
                            ? reportModule.generatePremiumReport.bind(reportModule)
                            : typeof reportModule === 'function'
                                ? reportModule
                                : null;

const fetchSupplementaryEvidence = typeof suppModule.fetchSupplementaryEvidence === 'function'
                            ? suppModule.fetchSupplementaryEvidence.bind(suppModule)
                            : typeof suppModule === 'function'
                                ? suppModule
                                : null;

const writeLog          = typeof loggerModule.writeLog === 'function'
                            ? loggerModule.writeLog.bind(loggerModule)
                            : typeof loggerModule === 'function'
                                ? loggerModule
                                : async () => {};   // safe no-op fallback

const resolveEntity     = typeof entityModule.resolveEntity === 'function'
                            ? entityModule.resolveEntity.bind(entityModule)
                            : typeof entityModule === 'function'
                                ? entityModule
                                : null;

// ── Input validation ────────────────────────────────────────────────────────
function isValidUrl(str) {
    try {
        const u = new URL(str.startsWith('http') ? str : 'https://' + str);
        return u.hostname.includes('.');
    } catch { return false; }
}

function normaliseUrl(str) {
    if (!str) return null;
    const s = str.trim();
    return s.startsWith('http') ? s : 'https://' + s;
}

// ── Safely call writeLog without crashing if it doesn't return a Promise ───
function safeWriteLog(payload) {
    try {
        const result = writeLog(payload);
        if (result && typeof result.catch === 'function') {
            result.catch(err => console.warn('[HAI] Log write failed:', err.message));
        }
    } catch (err) {
        console.warn('[HAI] Log write threw:', err.message);
    }
}

// ── Route handler ───────────────────────────────────────────────────────────
router.post('/', async (req, res) => {
    const startTime = Date.now();

    const rawUrl    = (req.body.url      || '').trim();
    const company   = (req.body.company  || '').trim();
    const industry  = (req.body.industry || 'Technology').trim();
    const stage     = (req.body.stage    || 'startup').trim();
    const size      = (req.body.size     || '1-10').trim();

    if (!rawUrl)            return res.status(400).json({ success: false, data: 'URL is required.' });
    if (!isValidUrl(rawUrl)) return res.status(400).json({ success: false, data: 'Invalid URL provided.' });
    if (!company)           return res.status(400).json({ success: false, data: 'Company name is required.' });
    if (!scrape)            return res.status(500).json({ success: false, data: 'Scraper service not available.' });
    if (!callOpenAI)        return res.status(500).json({ success: false, data: 'Evaluation service not available.' });

    const url        = normaliseUrl(rawUrl);
    const analysisId = uuidv4();

    console.log(`[HAI /evaluate] id=${analysisId} company="${company}" url=${url}`);

    try {

        // ── Step 0: Entity resolution ──────────────────────────────────────
        let entityProfile = null;
        let queryName     = company;

        if (resolveEntity) {
            try {
                entityProfile = await resolveEntity(company, url);
                queryName     = entityProfile.resolvedName || company;
                console.log(`[HAI] Entity resolved: "${queryName}" confidence=${entityProfile.overallConfidence}`);
            } catch (entityErr) {
                console.warn('[HAI] Entity resolution failed (non-blocking):', entityErr.message);
            }
        }

        if (!entityProfile) {
            entityProfile = {
                inputName: company, inputUrl: url, resolvedName: company,
                resolvedDomain: null, wikidataId: null, lei: null, cik: null,
                isPublicCompany: false, resolvedIndustry: null,
                nameMatchScore: 0, domainVerified: null,
                domainMatchConfidence: 0, edgarCrossCheckFound: false,
                overallConfidence: 0,
                warnings: [],
                wikidataIsOneSignal: true,
                resolvedAt: new Date().toISOString()
            };
        }

        // ── Step 1: Scrape ─────────────────────────────────────────────────
        console.log(`[HAI] Scraping: ${url}`);
        let scrapeResult = {};
        try {
            scrapeResult = await scrape(url) || {};
        } catch (scrapeErr) {
            console.warn('[HAI] Scraper threw (treating as blocked):', scrapeErr.message);
            scrapeResult = { combined_text: '', scraped_pages: [], scrape_status: 'blocked', limited_access: false, partial_scrape: false };
        }

        const combined_text  = scrapeResult.combined_text  || '';
        const scraped_pages  = scrapeResult.scraped_pages  || [];
        const scrape_status  = scrapeResult.scrape_status  || 'blocked';
        const limited_access = scrapeResult.limited_access || false;
        const partial_scrape = scrapeResult.partial_scrape || false;

        console.log(`[HAI] Scrape status=${scrape_status} pages=${scraped_pages.length} chars=${combined_text.length}`);

        // ── Step 2: Supplementary evidence ────────────────────────────────
        let supplementarySignals = null;
        const needsSupplementary = partial_scrape || limited_access ||
            scrape_status === 'partial' || scrape_status === 'limited' ||
            scrape_status === 'blocked' || combined_text.length < 500;

        if (needsSupplementary && fetchSupplementaryEvidence) {
            console.log('[HAI] Fetching supplementary evidence...');
            try {
                supplementarySignals = await fetchSupplementaryEvidence(
                    queryName, url, industry,
                    { entityProfile, combinedText: combined_text }
                );
                console.log(`[HAI] Supplementary signals: ${supplementarySignals?.totalSignals ?? 0} total`);
            } catch (suppErr) {
                console.warn('[HAI] Supplementary evidence failed (non-blocking):', suppErr.message);
            }
        }

        // ── Step 3: OpenAI key guard ───────────────────────────────────────
        if (!process.env.OPENAI_API_KEY) {
            console.error('[HAI] OPENAI_API_KEY not set');
            return res.status(500).json({ success: false, data: 'Evaluation service is not configured.' });
        }

        // ── Step 4: OpenAI evaluation ──────────────────────────────────────
        console.log('[HAI] Calling OpenAI...');
        let evaluation = null;
        try {
            evaluation = await callOpenAI(combined_text, company, industry);
            console.log(`[HAI] OpenAI complete. Criteria: ${Object.keys(evaluation || {}).length}`);
        } catch (aiErr) {
            console.error('[HAI] OpenAI failed:', aiErr.message);
            return res.status(500).json({ success: false, data: 'Evaluation could not be completed. Please try again.' });
        }

        // ── Step 5: Premium report ─────────────────────────────────────────
        let premiumReport   = null;
        let evaluationState = 'valid';
        let calibration     = null;

        if (generatePremiumReport) {
            try {
                const reportResult = await generatePremiumReport(
                    evaluation, combined_text, supplementarySignals,
                    company, industry, stage, size
                );
                premiumReport   = reportResult.premiumReport   || null;
                evaluationState = reportResult.evaluationState || 'valid';
                calibration     = reportResult.calibration     || null;
                console.log(`[HAI] Premium report state=${evaluationState}`);
            } catch (reportErr) {
                console.warn('[HAI] Premium report failed (non-blocking):', reportErr.message);
            }
        }

        // ── Step 6: Log phase 1 (fire-and-forget) ─────────────────────────
        safeWriteLog({
            analysis_id:           analysisId,
            company_name:          company,
            company_url:           url,
            industry, stage, size,
            scrape_status,
            limited_access_flag:   limited_access || false,
            evaluation_state:      evaluationState,
            edgar_signals:         supplementarySignals?.edgarSignals    ?? 0,
            wayback_signals:       supplementarySignals?.waybackSignals  ?? 0,
            oecd_signals:          supplementarySignals?.oecdSignals     ?? 0,
            github_signals:        supplementarySignals?.githubSignals   ?? 0,
            academic_signals:      supplementarySignals?.academicSignals ?? 0,
            supplementary_total:   supplementarySignals?.totalSignals    ?? 0,
            entity_resolved_name:  entityProfile?.resolvedName           ?? '',
            entity_wikidata_id:    entityProfile?.wikidataId             ?? '',
            entity_is_public:      entityProfile?.isPublicCompany        ?? false,
            entity_confidence:     entityProfile?.overallConfidence       ?? 0,
            entity_domain_match:   entityProfile?.domainVerified         ?? null,
            has_overrides:         supplementarySignals?.impact?.hasOverrides  ?? false,
            override_count:        supplementarySignals?.impact?.negativeOverrides?.length ?? 0,
            worst_override:        supplementarySignals?.impact?.worstSeverity  ?? '',
        });

        // ── Step 7: Respond ────────────────────────────────────────────────
        console.log(`[HAI /evaluate] Done in ${Date.now() - startTime}ms`);

        return res.json({
            success: true,
            data: {
                analysis_id:           analysisId,
                evaluation:            evaluation        || {},
                scraped_pages,
                limited_access:        limited_access    || false,
                partial_scrape:        partial_scrape    || false,
                scraper_blocked:       scrape_status === 'blocked',
                scrape_status,
                premiumReport,
                evaluation_state:      evaluationState,
                calibration,
                supplementary_signals: supplementarySignals,
                entityProfile,
            }
        });

    } catch (err) {
        // Log the full error so Railway logs show what actually failed
        console.error('[HAI /evaluate] Unhandled error:', err.message);
        console.error('[HAI /evaluate] Stack:', err.stack);
        return res.status(500).json({
            success: false,
            data: 'An unexpected error occurred. Please try again.',
        });
    }
});

module.exports = router;
