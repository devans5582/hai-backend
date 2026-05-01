'use strict';

// src/routes/evaluate.js
// POST /evaluate — Phase 6

const express    = require('express');
const router     = express.Router();
const { v4: uuidv4 } = require('uuid');

const scraper    = require('../services/scraper');
const openai     = require('../services/openai');
const reporter   = require('../services/report-generator');
const supp       = require('../services/supplementary-evidence');
const logger     = require('../services/analysis-logger');
const entity     = require('../services/entity-resolver');

// ── Resolve function regardless of how each service exports it ─────────────
// Handles: module.exports = fn  OR  module.exports = { methodName: fn }
function resolve(mod, ...names) {
    if (typeof mod === 'function') return mod;
    for (const name of names) {
        if (mod && typeof mod[name] === 'function') return mod[name].bind(mod);
    }
    // Last resort: find any exported function
    if (mod && typeof mod === 'object') {
        const fn = Object.values(mod).find(v => typeof v === 'function');
        if (fn) return fn;
    }
    return null;
}

const doScrape         = resolve(scraper,  'scrape', 'scrapeUrl', 'fetchPages', 'run');
const doCallOpenAI     = resolve(openai,   'callOpenAI', 'evaluate', 'run', 'call');
const doReport         = resolve(reporter, 'generatePremiumReport', 'generate', 'run');
const doSupplementary  = resolve(supp,     'fetchSupplementaryEvidence', 'fetch', 'run');
const doWriteLog       = resolve(logger,   'writeLog', 'log', 'write', 'insert');
const doResolveEntity  = resolve(entity,   'resolveEntity', 'resolve', 'lookup');

// Log what was found at startup so Railway logs show the export shapes
console.log('[HAI] Service exports resolved:',
    'scraper=' + (doScrape ? 'OK' : 'NULL'),
    'openai='  + (doCallOpenAI ? 'OK' : 'NULL'),
    'report='  + (doReport ? 'OK' : 'NULL'),
    'supp='    + (doSupplementary ? 'OK' : 'NULL'),
    'logger='  + (doWriteLog ? 'OK' : 'NULL'),
    'entity='  + (doResolveEntity ? 'OK' : 'NULL')
);

// ── Helpers ─────────────────────────────────────────────────────────────────
function isValidUrl(str) {
    try { return new URL(str.startsWith('http') ? str : 'https://' + str).hostname.includes('.'); }
    catch { return false; }
}

function normaliseUrl(str) {
    const s = (str || '').trim();
    return s.startsWith('http') ? s : 'https://' + s;
}

function safeLog(payload) {
    if (!doWriteLog) return;
    try {
        const r = doWriteLog(payload);
        if (r && typeof r.catch === 'function') r.catch(e => console.warn('[HAI] Log failed:', e.message));
    } catch (e) { console.warn('[HAI] Log threw:', e.message); }
}

// ── Route ────────────────────────────────────────────────────────────────────
router.post('/', async (req, res) => {
    const t0 = Date.now();

    const rawUrl   = (req.body.url      || '').trim();
    const company  = (req.body.company  || '').trim();
    const industry = (req.body.industry || 'Technology').trim();
    const stage    = (req.body.stage    || 'startup').trim();
    const size     = (req.body.size     || '1-10').trim();

    if (!rawUrl || !isValidUrl(rawUrl))
        return res.status(400).json({ success: false, data: 'A valid URL is required.' });
    if (!company)
        return res.status(400).json({ success: false, data: 'Company name is required.' });

    const url        = normaliseUrl(rawUrl);
    const analysisId = uuidv4();
    console.log(`[HAI] START id=${analysisId} company="${company}" url=${url}`);

    try {

        // ── Step 0: Entity resolution (non-blocking) ───────────────────────
        let entityProfile = { inputName: company, inputUrl: url, resolvedName: company,
            resolvedDomain: null, wikidataId: null, lei: null, cik: null,
            isPublicCompany: false, resolvedIndustry: null, nameMatchScore: 0,
            domainVerified: null, domainMatchConfidence: 0, edgarCrossCheckFound: false,
            overallConfidence: 0, warnings: [], wikidataIsOneSignal: true,
            resolvedAt: new Date().toISOString() };
        let queryName = company;

        if (doResolveEntity) {
            try {
                entityProfile = await doResolveEntity(company, url);
                queryName = entityProfile.resolvedName || company;
                console.log(`[HAI] Entity: "${queryName}" conf=${entityProfile.overallConfidence}`);
            } catch (e) { console.warn('[HAI] Entity resolution failed (non-blocking):', e.message); }
        }

        // ── Step 1: Scrape ─────────────────────────────────────────────────
        let combined_text = '', scraped_pages = [], scrape_status = 'blocked';
        let limited_access = false, partial_scrape = false;

        if (doScrape) {
            try {
                console.log(`[HAI] Scraping ${url}`);
                const r = await doScrape(url) || {};
                combined_text  = r.combined_text  || '';
                scraped_pages  = r.scraped_pages  || [];
                scrape_status  = r.scrape_status  || (combined_text.length > 100 ? 'ok' : 'blocked');
                limited_access = r.limited_access || false;
                partial_scrape = r.partial_scrape || false;
                console.log(`[HAI] Scrape: status=${scrape_status} pages=${scraped_pages.length} chars=${combined_text.length}`);
            } catch (e) {
                console.warn('[HAI] Scraper failed (treating as blocked):', e.message);
                scrape_status = 'blocked';
            }
        } else {
            console.warn('[HAI] Scraper not available — proceeding with supplementary only');
        }

        // ── Step 2: Supplementary evidence ────────────────────────────────
        let supplementarySignals = null;
        const needsSupp = !doScrape || partial_scrape || limited_access ||
            scrape_status === 'partial' || scrape_status === 'limited' ||
            scrape_status === 'blocked' || combined_text.length < 500;

        if (needsSupp && doSupplementary) {
            console.log('[HAI] Fetching supplementary evidence...');
            try {
                supplementarySignals = await doSupplementary(
                    queryName, url, industry,
                    { entityProfile, combinedText: combined_text }
                );
                console.log(`[HAI] Supplementary: ${supplementarySignals?.totalSignals ?? 0} items`);
            } catch (e) { console.warn('[HAI] Supplementary failed (non-blocking):', e.message); }
        }

        // ── Step 3: OpenAI key guard ───────────────────────────────────────
        if (!process.env.OPENAI_API_KEY) {
            console.error('[HAI] OPENAI_API_KEY not set');
            return res.status(500).json({ success: false, data: 'Evaluation service is not configured. Please contact support.' });
        }

        // ── Step 4: OpenAI evaluation ──────────────────────────────────────
        if (!doCallOpenAI) {
            console.error('[HAI] OpenAI service not resolvable');
            return res.status(500).json({ success: false, data: 'Evaluation service is not available.' });
        }

        let evaluation = null;
        try {
            console.log('[HAI] Calling OpenAI...');
            evaluation = await doCallOpenAI(combined_text, company, industry);
            console.log(`[HAI] OpenAI complete. Criteria: ${Object.keys(evaluation || {}).length}`);
        } catch (e) {
            console.error('[HAI] OpenAI failed:', e.message);
            return res.status(500).json({ success: false, data: 'Evaluation could not be completed. Please try again.' });
        }

        // ── Step 5: Premium report (non-blocking) ──────────────────────────
        let premiumReport = null, evaluationState = 'valid', calibration = null;

        if (doReport) {
            try {
                console.log('[HAI] Calling generatePremiumReport...');
                const r = await doReport(
                    evaluation,
                    combined_text,
                    {
                        company,
                        industry,
                        stage,
                        size,
                        partialScrape:  partial_scrape,
                        limitedAccess:  limited_access,
                        scrapeStatus:   scrape_status,
                        scrapedPages:   scraped_pages,
                        supplementarySignals,
                        entityProfile
                    }
                );
                console.log('[HAI] Report raw return type:', typeof r, '| keys:', r ? Object.keys(r).join(',') : 'null');

                // Handle both possible return shapes:
                // Shape A: { premiumReport: {...}, evaluationState: '...', calibration: {...} }
                // Shape B: the premiumReport object directly (has 'snapshot', 'pillars', etc.)
                if (r && r.premiumReport) {
                    // Shape A — wrapped
                    premiumReport   = r.premiumReport;
                    evaluationState = r.evaluationState || r.evaluation_state || 'valid';
                    calibration     = r.calibration || null;
                } else if (r && (r.snapshot || r.pillars || r.executive_summary || r.signal_profile)) {
                    // Shape B — premiumReport IS the return value
                    premiumReport   = r;
                    evaluationState = r.evaluation_state || 'valid';
                    calibration     = r.calibration || null;
                } else if (r) {
                    // Unknown shape — log all keys so Railway logs show us what we got
                    console.warn('[HAI] Unexpected report shape. Keys:', Object.keys(r).join(', '));
                    premiumReport = null;
                }

                console.log(`[HAI] Report resolved: state=${evaluationState} hasReport=${!!premiumReport} reportKeys=${premiumReport ? Object.keys(premiumReport).join(',') : 'none'}`);
            } catch (e) {
                console.error('[HAI] Premium report FAILED:', e.message);
                console.error('[HAI] Report stack:', e.stack);
            }
        } else {
            console.warn('[HAI] doReport is null — report-generator.js export not resolved');
        }

        // ── Step 6: Log ────────────────────────────────────────────────────
        safeLog({
            analysis_id: analysisId, company_name: company, company_url: url,
            industry, stage, size, scrape_status,
            limited_access_flag:  limited_access || false,
            evaluation_state:     evaluationState,
            edgar_signals:        supplementarySignals?.edgarSignals    ?? 0,
            wayback_signals:      supplementarySignals?.waybackSignals  ?? 0,
            oecd_signals:         supplementarySignals?.oecdSignals     ?? 0,
            github_signals:       supplementarySignals?.githubSignals   ?? 0,
            academic_signals:     supplementarySignals?.academicSignals ?? 0,
            supplementary_total:  supplementarySignals?.totalSignals    ?? 0,
            entity_resolved_name: entityProfile?.resolvedName           ?? '',
            entity_is_public:     entityProfile?.isPublicCompany        ?? false,
            entity_confidence:    entityProfile?.overallConfidence       ?? 0,
        });

        // ── Step 7: Respond ────────────────────────────────────────────────
        console.log(`[HAI] DONE in ${Date.now() - t0}ms`);
        return res.json({
            success: true,
            data: {
                analysis_id: analysisId,
                evaluation:  evaluation || {},
                scraped_pages, limited_access, partial_scrape,
                scraper_blocked:  scrape_status === 'blocked',
                scrape_status,
                premiumReport, evaluation_state: evaluationState, calibration,
                supplementary_signals: supplementarySignals,
                entityProfile,
            }
        });

    } catch (err) {
        console.error('[HAI /evaluate] Unhandled:', err.message, '\n', err.stack);
        return res.status(500).json({ success: false, data: 'An unexpected error occurred. Please try again.' });
    }
});

module.exports = router;
