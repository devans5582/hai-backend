'use strict';

const { Router } = require('express');
const router = Router();

const { scrapeCompanyPages }    = require('../services/scraper');
const { callOpenAI }             = require('../services/openai');
const { generatePremiumReport } = require('../services/report-generator');

// POST /evaluate
//
// Accepts: application/x-www-form-urlencoded  { url: "https://example.com" }
//          application/json                   { "url": "https://example.com" }
//
// The frontend (main.js) also sends an "action" field in the form body
// (e.g. action=humaital_auto_evaluate_api) — this is a WordPress AJAX
// convention. It is silently ignored here; Express parses it into req.body
// but we never read it.
//
// Returns the same JSON shape as the WordPress snippet so main.js
// handleSuccess requires zero changes:
//
//   Success:
//     { success: true, data: { evaluation: {...}, scraped_pages: [...],
//                              scraped_text_preview: "...", limited_access: false } }
//
//   Soft failure (site blocked):
//     { success: true, data: { evaluation: {}, scraped_pages: [],
//                              scraper_blocked: true, message: "..." } }
//
//   Hard failure:
//     { success: false, data: "Error message string" }

router.post('/', async (req, res) => {

    const requestStart = Date.now();

    // ----------------------------------------------------------------
    // 1. Validate input
    // ----------------------------------------------------------------

    // "action" field from the WordPress AJAX convention is present in req.body
    // but deliberately not read. No special handling needed — it is ignored.
    const rawUrl = (req.body && (req.body.url || req.body.URL)) || '';

    if (!rawUrl || !rawUrl.trim()) {
        console.warn('[evaluate] Request rejected: missing URL field');
        return res.status(200).json({
            success: false,
            data: 'URL is required.'
        });
    }

    // Ensure URL has a scheme — matches WordPress snippet behavior
    let targetUrl = rawUrl.trim();
    if (!/^https?:\/\//i.test(targetUrl)) {
        targetUrl = 'https://' + targetUrl;
    }

    console.log(`[evaluate] Request received — target: ${targetUrl}`);

    // ----------------------------------------------------------------
    // 2. Scrape the company's public pages
    // ----------------------------------------------------------------
    console.log(`[evaluate] Scraping started — ${targetUrl}`);
    const scrapeStart = Date.now();

    let scrapeResult;
    try {
        scrapeResult = await scrapeCompanyPages(targetUrl);
    } catch (err) {
        // scrapeCompanyPages is designed not to throw — this is a last-resort catch
        console.error(`[evaluate] Scraper threw unexpectedly (${Date.now() - scrapeStart}ms): ${err.message}`);
        return res.status(200).json({
            success: true,
            data: {
                evaluation:      {},
                scraped_pages:   [],
                scraper_blocked: true,
                message:         'Evidence could not be automatically obtained from the company website.'
            }
        });
    }

    console.log(`[evaluate] Scraping finished — ${Date.now() - scrapeStart}ms — pages: ${scrapeResult.scraped_pages ? scrapeResult.scraped_pages.length : 0} — blocked: ${!!scrapeResult.scraper_blocked}`);

    // Scraper returns scraper_blocked: true when the site was completely unreachable
    if (scrapeResult.scraper_blocked) {
        console.warn(`[evaluate] Returning scraper_blocked result — ${targetUrl}`);
        return res.status(200).json({
            success: true,
            data: {
                evaluation:      {},
                scraped_pages:   [],
                scraper_blocked: true,
                message:         scrapeResult.message || 'Evidence could not be automatically obtained from the company website.'
            }
        });
    }

    // ----------------------------------------------------------------
    // 3. Guard: OpenAI key must be configured
    // ----------------------------------------------------------------
    if (!process.env.OPENAI_API_KEY) {
        console.error('[evaluate] OPENAI_API_KEY is not set — cannot call OpenAI');
        return res.status(200).json({
            success: false,
            data: 'API Key not configured in backend.'
        });
    }

    // ----------------------------------------------------------------
    // 4. Call OpenAI with the scraped text
    // ----------------------------------------------------------------
    console.log(`[evaluate] OpenAI call started — text length: ${scrapeResult.combined_text.length} chars`);
    const aiStart = Date.now();

    let evaluationData;
    try {
        evaluationData = await callOpenAI(scrapeResult.combined_text);
    } catch (err) {
        console.error(`[evaluate] OpenAI call failed (${Date.now() - aiStart}ms): ${err.message}`);
        return res.status(200).json({
            success: false,
            data: 'Failed to connect to OpenAI API: ' + err.message
        });
    }

    console.log(`[evaluate] OpenAI call finished — ${Date.now() - aiStart}ms`);

    // ----------------------------------------------------------------
    // 5A. Generate premium report narrative (Phase 3)
    //
    // Runs AFTER evaluationData is populated. Uses evaluationData and
    // scraped text only — does NOT compute scores, confidence, or
    // certification status (those belong to the frontend).
    //
    // snapshot fields (alignment_level, evidence_strength,
    // certification_status, benchmark_position) are returned as null
    // and populated by the frontend after exact score calculations.
    //
    // Fail-safe: any failure sets premiumReport to null without
    // affecting the evaluation response or downstream PDF/email flow.
    // ----------------------------------------------------------------
    console.log(`[evaluate] Premium report generation started`);
    const reportStart = Date.now();
    let premiumReport = null;

    try {
        premiumReport = await generatePremiumReport(
            evaluationData,
            scrapeResult.combined_text
        );
        console.log(`[evaluate] Premium report generation finished — ${Date.now() - reportStart}ms — success: ${premiumReport !== null}`);
    } catch (err) {
        // generatePremiumReport is designed not to throw — this is a last-resort catch
        console.warn(`[evaluate] Premium report threw unexpectedly (${Date.now() - reportStart}ms):`, err.message);
        premiumReport = null;
    }

    // ----------------------------------------------------------------
    // 5B. Return — all original fields preserved, premiumReport added
    //
    // main.js reads:
    //   resData.data.evaluation      → applied to assessmentState by criterion key
    //   resData.data.scraped_pages   → stored as window.currentScrapedPages
    //   resData.data.scraper_blocked → stored as window.scraperBlocked
    //   resData.data.message         → shown in warning when scraper_blocked
    //   resData.data.premiumReport   → NEW: stored as window.currentPremiumReport
    //   (scraped_text_preview and limited_access are returned but not consumed)
    // ----------------------------------------------------------------
    const totalMs = Date.now() - requestStart;
    console.log(`[evaluate] Request complete — ${totalMs}ms — ${targetUrl}`);

    return res.status(200).json({
        success: true,
        data: {
            evaluation:           evaluationData,
            scraped_pages:        scrapeResult.scraped_pages,
            scraped_text_preview: scrapeResult.combined_text.slice(0, 5000),
            limited_access:       scrapeResult.limited_access,
            premiumReport:        premiumReport
        }
    });
});

module.exports = router;
