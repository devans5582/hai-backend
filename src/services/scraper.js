'use strict';

const axios = require('axios');
const { URL } = require('url');

// ---------------------------------------------------------------
// Constants — replicated verbatim from the WordPress snippet
// ---------------------------------------------------------------

const USER_AGENT =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
    'AppleWebKit/537.36 (KHTML, like Gecko) ' +
    'Chrome/120.0.0.0 Safari/537.36';

const GOVERNANCE_KEYWORDS = [
    'privacy', 'trust', 'security', 'governance', 'compliance',
    'transparency', 'ethic', 'principle', 'legal', 'policy',
    'terms of use', 'terms of service'
];

const FORCED_PATHS = [
    '/privacy', '/terms', '/ai-policy',
    '/responsible-ai', '/trust', '/ethics', '/governance'
];

const BLOCK_KEYWORDS = [
    'Just a moment...', 'Cloudflare', 'Access Denied',
    'Security challenge', 'Please enable JS', 'enable JavaScript',
    'Not Acceptable', 'Attention Required!', 'Pardon Our Interruption'
];

const BLOCK_STATUS_CODES    = [403, 406, 429, 503];
const MAX_DISCOVERED_LINKS  = 5;
const MAX_CHARS             = 30000;
const LIMITED_ACCESS_THRESHOLD = 1000;


// ---------------------------------------------------------------
// Main export
// ---------------------------------------------------------------

/**
 * Scrapes a company's public governance pages and returns combined text.
 *
 * Designed NOT to throw. All errors are caught and returned as
 * scraper_blocked so the caller always gets a usable value.
 *
 * @param {string} targetUrl
 * @returns {Promise<{scraper_blocked, combined_text?, scraped_pages?, limited_access?, message?}>}
 */
async function scrapeCompanyPages(targetUrl) {

    // ----------------------------------------------------------------
    // Step 1: Fetch the homepage
    // ----------------------------------------------------------------
    let homepageHtml;
    try {
        const resp = await axios.get(targetUrl, {
            timeout: 15000,
            headers: { 'User-Agent': USER_AGENT },
            validateStatus: () => true,
            maxRedirects: 5
        });

        const body = resp.data ? String(resp.data) : '';
        if (!body || body.trim().length === 0) {
            console.warn(`[scraper] Homepage returned empty body — ${targetUrl}`);
            return blocked('Evidence could not be automatically obtained from the company website.');
        }
        homepageHtml = body;
    } catch (err) {
        if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
            console.warn(`[scraper] Homepage fetch timed out (15s) — ${targetUrl}`);
        } else {
            console.warn(`[scraper] Homepage fetch failed (${err.code || err.message}) — ${targetUrl}`);
        }
        return blocked('Evidence could not be automatically obtained from the company website.');
    }

    // ----------------------------------------------------------------
    // Step 2: Parse base URL
    // ----------------------------------------------------------------
    let parsedBase;
    try {
        parsedBase = new URL(targetUrl);
    } catch (_) {
        console.warn(`[scraper] Invalid URL format — ${targetUrl}`);
        return blocked('Invalid URL format.');
    }
    const baseOrigin = parsedBase.origin;
    const baseHost   = parsedBase.hostname;

    // ----------------------------------------------------------------
    // Step 3: Build page list
    // ----------------------------------------------------------------
    const pagesToScrape = [targetUrl];

    for (const path of FORCED_PATHS) {
        pagesToScrape.push(baseOrigin + path);
    }

    const discoveredLinks = discoverGovernanceLinks(homepageHtml, targetUrl, baseOrigin, baseHost);
    let discoveredCount = 0;
    for (const link of discoveredLinks) {
        if (discoveredCount >= MAX_DISCOVERED_LINKS) break;
        if (!pagesToScrape.includes(link)) {
            pagesToScrape.push(link);
            discoveredCount++;
        }
    }

    const uniquePages = [...new Set(pagesToScrape)];
    console.log(`[scraper] Page list built — ${uniquePages.length} URLs (${discoveredCount} discovered from homepage)`);

    // ----------------------------------------------------------------
    // Step 4: Fetch each page and extract text
    // ----------------------------------------------------------------
    let combinedText      = '';
    const successfulPages = [];

    for (const pageUrl of uniquePages) {
        try {
            const resp = await axios.get(pageUrl, {
                timeout: 10000,
                headers: { 'User-Agent': USER_AGENT },
                validateStatus: () => true,
                maxRedirects: 3
            });

            const statusCode = resp.status;
            const pageHtml   = resp.data ? String(resp.data) : '';

            if (BLOCK_STATUS_CODES.includes(statusCode)) {
                console.log(`[scraper] Skipped HTTP ${statusCode} — ${pageUrl}`);
                continue;
            }
            if (isBlockedPage(pageHtml)) {
                console.log(`[scraper] Skipped firewall/captcha — ${pageUrl}`);
                continue;
            }
            if (pageHtml.trim().length < 300) {
                console.log(`[scraper] Skipped body too short — ${pageUrl}`);
                continue;
            }

            const cleanText = extractText(pageHtml);
            combinedText   += `\n\n--- Content from ${pageUrl} ---\n\n` + cleanText;
            successfulPages.push(pageUrl);
            console.log(`[scraper] OK ${pageUrl} (${cleanText.length} chars)`);

        } catch (err) {
            // Per-page errors are logged and skipped — matches WordPress behavior
            if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
                console.log(`[scraper] Skipped timeout (10s) — ${pageUrl}`);
            } else {
                console.log(`[scraper] Skipped fetch error (${err.code || err.message}) — ${pageUrl}`);
            }
        }
    }

    // ----------------------------------------------------------------
    // Step 5: Assess limited_access and truncate
    // ----------------------------------------------------------------
    const limitedAccess = combinedText.trim().length < LIMITED_ACCESS_THRESHOLD;

    if (limitedAccess) {
        console.warn(`[scraper] limited_access=true — total text under ${LIMITED_ACCESS_THRESHOLD} chars`);
    }

    if (combinedText.length > MAX_CHARS) {
        console.log(`[scraper] Truncating ${combinedText.length} chars to ${MAX_CHARS}`);
        combinedText = combinedText.slice(0, MAX_CHARS) + '... [TRUNCATED]';
    }

    console.log(`[scraper] Complete — ${successfulPages.length}/${uniquePages.length} pages OK, ${combinedText.length} chars`);

    return {
        scraper_blocked: false,
        combined_text:   combinedText,
        scraped_pages:   successfulPages,
        limited_access:  limitedAccess
    };
}


// ---------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------

function blocked(message) {
    return { scraper_blocked: true, message };
}

function isBlockedPage(html) {
    const lower = html.toLowerCase();
    for (const kw of BLOCK_KEYWORDS) {
        if (lower.includes(kw.toLowerCase())) return true;
    }
    return false;
}

function discoverGovernanceLinks(html, targetUrl, baseOrigin, baseHost) {
    const links = [];
    const anchorRegex = /<a\s[^>]*href=["']([^"'#?][^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
    let match;

    while ((match = anchorRegex.exec(html)) !== null) {
        let href = match[1].trim();
        const text = (match[2] || '').replace(/<[^>]+>/g, '').toLowerCase().trim();

        const relevant = GOVERNANCE_KEYWORDS.some(kw =>
            text.includes(kw) || href.toLowerCase().includes(kw)
        );
        if (!relevant) continue;

        if (!/^https?:\/\//i.test(href)) {
            href = href.startsWith('/') ? baseOrigin + href : targetUrl.replace(/\/?$/, '/') + href;
        }

        try {
            const parsed = new URL(href);
            if (!parsed.hostname.includes(baseHost) && !baseHost.includes(parsed.hostname)) continue;
            href = parsed.origin + parsed.pathname;
        } catch (_) {
            continue;
        }

        if (!links.includes(href)) links.push(href);
    }

    return links;
}

function extractText(html) {
    let text = html.replace(/<script[\s\S]*?<\/script>/gi, '');
    text = text.replace(/<style[\s\S]*?<\/style>/gi, '');
    text = text.replace(/<[^>]+>/g, '');
    text = text.replace(/\s+/g, ' ').trim();
    return text;
}


module.exports = { scrapeCompanyPages };
