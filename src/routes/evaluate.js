'use strict';

// src/routes/evaluate.js
// POST /evaluate — Phase 6

const express    = require('express');
const router     = express.Router();
const { v4: uuidv4 } = require('uuid');
const axios      = require('axios');

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

    // Optional direct governance page URLs submitted by the user.
    // Sent when the company's site blocks automated scraping (e.g. Wells Fargo,
    // Snowflake) so the user can paste specific governance/AI-policy page URLs.
    // Passed through to the scraper, which fetches them first — before FORCED_PATHS —
    // so real governance text reaches OpenAI instead of the calibration floor.
    // Accepts: comma-separated string OR repeated directUrl[] form fields.
    // URLSearchParams encodes repeated keys as directUrl[]=... or directUrl=...
    const _rawDirect = req.body.directUrls || req.body['directUrls[]'] || '';
    const directUrls = (Array.isArray(_rawDirect) ? _rawDirect : String(_rawDirect).split(','))
        .map(u => u.trim())
        .filter(u => u.length > 0 && u.includes('.'));

    if (!rawUrl || !isValidUrl(rawUrl))
        return res.status(400).json({ success: false, data: 'A valid URL is required.' });
    if (!company)
        return res.status(400).json({ success: false, data: 'Company name is required.' });

    const url        = normaliseUrl(rawUrl);
    const analysisId = uuidv4();
    console.log(`[HAI] START id=${analysisId} company="${company}" url=${url}`);

    try {

        // ── Deduplication check — reject re-assessment within 7 days ───────
        // Queries hai_analysis_logs for a successfully delivered evaluation of the
        // same domain in the last 7 days. Uses company_url ilike match so no
        // extra target_domain column is needed. Failures are non-blocking — a
        // Supabase outage never prevents an assessment from running.
        if (process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_KEY) {
            try {
                let targetDomain = '';
                try { targetDomain = new URL(url).hostname.replace(/^www\./, ''); } catch (_) {}

                if (targetDomain) {
                    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
                    const dedupResp = await axios.get(
                        `${process.env.SUPABASE_URL}/rest/v1/hai_analysis_logs`,
                        {
                            timeout: 5000,
                            headers: {
                                'apikey':        process.env.SUPABASE_SERVICE_KEY,
                                'Authorization': 'Bearer ' + process.env.SUPABASE_SERVICE_KEY,
                            },
                            params: {
                                select:                  'analysis_id,timestamp,final_score,email_delivery_status',
                                // target_domain is an exact-match column populated from Phase 6.2.
                                // Falls back to ilike on company_url for rows logged before
                                // the target_domain column was added.
                                target_domain:           `eq.${targetDomain}`,
                                timestamp:               `gte.${sevenDaysAgo}`,
                                // Only block on rows that were actually delivered or in-flight
                                // (not on rows that were hard-blocked by the delivery gate).
                                'email_delivery_status': 'not.ilike.blocked*',
                                order:                   'timestamp.desc',
                                limit:                   1,
                            },
                            validateStatus: () => true,
                        }
                    );

                    if (dedupResp.status === 200 && Array.isArray(dedupResp.data) && dedupResp.data.length > 0) {
                        const prior = dedupResp.data[0];
                        const priorDate = new Date(prior.timestamp).toLocaleDateString('en-GB', {
                            day: 'numeric', month: 'long', year: 'numeric'
                        });
                        const score = prior.final_score != null ? ` (score: ${prior.final_score})` : '';
                        console.log(`[HAI] DEDUP block — ${targetDomain} assessed ${priorDate}, id=${prior.analysis_id}`);
                        return res.json({
                            success: false,
                            data: `This organisation was assessed on ${priorDate}${score}. ` +
                                  `Re-assessment is available after the 7-day window to ensure scoring integrity. ` +
                                  `Assessment ID: ${prior.analysis_id}`
                        });
                    }
                }
            } catch (dedupErr) {
                // Non-blocking — log and continue regardless
                console.warn('[HAI] Dedup check failed (non-blocking):', dedupErr.message);
            }
        }
        // ── End deduplication check ────────────────────────────────────────

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
        let limited_access = false, partial_scrape = false, content_empty = false;
        let scrapeResult = null;

        if (doScrape) {
            try {
                console.log(`[HAI] Scraping ${url}`);
                const r = await doScrape(url, { directUrls }) || {};
                scrapeResult   = r;
                combined_text  = r.combined_text  || '';
                scraped_pages  = r.scraped_pages  || [];
                scrape_status  = r.scrape_status  || (combined_text.length > 100 ? 'ok' : 'blocked');
                limited_access = r.limited_access || false;
                partial_scrape = r.partial_scrape || false;
                content_empty  = r.content_empty  || false;
                const redirect_walls = r.redirect_wall_count || 0;
                // Treat as limited access when most forced governance paths were redirect walls
                // so supplementary evidence triggers and fills the coverage gap
                if (redirect_walls >= 3 && !limited_access) {
                    console.log(`[HAI] ${redirect_walls} redirect walls detected — treating as limited_access for supplementary trigger`);
                    limited_access = true;
                }
                console.log(`[HAI] Scrape: status=${scrape_status} pages=${scraped_pages.length} chars=${combined_text.length} content_empty=${content_empty} redirect_walls=${redirect_walls}`);
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
                        partialScrape: partial_scrape,
                        limitedAccess: limited_access,
                        // content_empty: scraper found sufficient total chars but almost all
                        // were stubs from blocked pages — real governance text < 500 chars.
                        // report-generator uses this to route as partial_evaluation instead
                        // of valid, preventing full uplift on stub-only content.
                        contentEmpty:  content_empty,
                        scrapeStatus: scrape_status,
                        scrapedPages: scraped_pages,
                        supplementarySignals,
                        entityProfile,
                        pageCharCounts: (scraped_pages || []).map(p =>
                            (p.content || p.text || p.body || '').length
                        )
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
        // writeLog expects { analysisId, targetUrl, reqBody, scrapeResult, premiumReport }
        // Pass both the structured shape writeLog needs AND the flat fields it reads
        // from reqBody, so all columns are populated in the Phase 1 INSERT.
        safeLog({
            analysisId,
            targetUrl:    url,
            reqBody: {
                company:  company,
                industry: industry,
                stage:    stage,
                size:     size,
            },
            scrapeResult: scrapeResult || { scrape_status, limited_access, content_empty },
            premiumReport: premiumReport || null,
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
