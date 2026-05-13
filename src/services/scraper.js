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
    // Original
    'privacy', 'trust', 'security', 'governance', 'compliance',
    'transparency', 'ethic', 'principle', 'legal', 'policy',
    'terms of use', 'terms of service',
    // Expanded — corporate responsibility, AI, ESG, risk
    'responsible', 'responsibility', 'corporate responsibility',
    'artificial intelligence', 'ai policy', 'ai governance',
    'machine learning', 'algorithm', 'automated',
    'risk', 'risk management', 'enterprise risk',
    'esg', 'environmental', 'social', 'sustainability',
    'annual report', 'public policy', 'regulatory',
    'about us', 'our values', 'mission', 'purpose',
    'human rights', 'data ethics', 'fairness',
    'technology', 'innovation', 'digital',
    'accountability', 'oversight', 'board',
    'investor relations', 'newsroom', 'press',
];

const FORCED_PATHS = [
    // Original governance paths
    '/privacy', '/terms', '/ai-policy',
    '/responsible-ai', '/trust', '/ethics', '/governance',
    // Corporate responsibility and ESG
    '/about', '/about-us', '/corporate-responsibility',
    '/responsibility', '/esg', '/sustainability',
    // Risk and compliance
    '/risk', '/compliance', '/regulatory',
    // AI and technology
    '/ai', '/artificial-intelligence', '/technology',
    // Investor and public accountability
    '/investor-relations', '/newsroom', '/public-policy',
    // Locale-prefixed paths used by large enterprises (Microsoft, Google, etc.)
    // microsoft.com/responsible-ai redirects to a wall; the real content is at:
    '/en-us/ai/responsible-ai',
    '/en-us/corporate-responsibility',
    '/en-us/about/responsible-ai',
    '/en-us/ai/principles-and-approach',
    // Common locale variants for other large enterprises
    '/en-gb/ai/responsible-ai',
    '/en/responsible-ai',
    '/en/ai-governance',
    '/en-us/trust-center',
    // IBM-specific — tactical addition; IBM's primary governance content is not
    // at standard paths.  Long-term fix is semantic homepage link discovery.
    // Direct URL submission (options.directUrls) is the preferred user-facing
    // workaround for IBM and similar enterprise sites.
    '/impact',
    '/topics/ai-ethics',
];

// Pages whose URL paths strongly suggest non-governance content.
// These are deprioritised: if they pass the redirect-wall check they are
// still scraped, but they only count toward real content if they contain
// at least one AI_GOVERNANCE_TERM (below).
const LOW_VALUE_PATH_PATTERNS = [
    '/fraud', '/scam', '/phishing', '/security-alert',
    '/opt-out', '/cookie', '/sitemap', '/careers',
    '/investor', '/press-release', '/news/',
];

// At least one of these terms must appear in a low-value page's clean text
// for it to be considered real governance content.
const AI_GOVERNANCE_TERMS = [
    'artificial intelligence', ' ai ', 'machine learning', 'algorithm',
    'automated decision', 'governance', 'responsible', 'ethics',
    'accountability', 'oversight', 'compliance', 'risk management',
    'data ethics', 'fairness', 'transparency', 'human rights',
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

// Minimum real (non-stub) text required for a valid evaluation.
// Stub lines written by the scraper when a page is blocked all start with
// "[page restricted", "[page empty", or "[page not retrieved".
// A combined_text that exceeds LIMITED_ACCESS_THRESHOLD but is composed
// almost entirely of these stubs must not be treated as a full valid scrape.
const REAL_CONTENT_THRESHOLD = 500;

// ── measureRealContent ────────────────────────────────────────────
// Strips every stub line from combined_text and returns the char count
// of what remains.  Used to set content_empty on the return value.
function measureRealContent(combinedText) {
    if (!combinedText) return 0;
    // Remove stub annotations added by the scraper for blocked/empty pages
    const stripped = combinedText
        .replace(/\[page restricted[^\]]*\]/gi, '')
        .replace(/\[page empty[^\]]*\]/gi, '')
        .replace(/\[page not retrieved[^\]]*\]/gi, '')
        .replace(/\[Fallback evaluation[^\]]*\]/gi, '')
        .replace(/\[Homepage:[^\]]*\]/gi, '')
        .replace(/--- Content from https?:\/\/\S+ ---/gi, '')
        .replace(/\s+/g, ' ')
        .trim();
    return stripped.length;
}


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
 * @param {object} [options]
 * @param {string[]} [options.directUrls]  — Optional user-supplied governance page URLs.
 *   Fetched first, before FORCED_PATHS, so companies whose sites block automated
 *   scraping (e.g. Wells Fargo, Snowflake) can receive real scores instead of the
 *   calibration floor. Direct URL content is exempt from the redirect-wall filter
 *   (the user explicitly provided the URL) but still flows through measureRealContent().
 * @returns {Promise<{scraper_blocked, combined_text?, scraped_pages?, limited_access?, message?}>}
 */
async function scrapeCompanyPages(targetUrl, options = {}) {
    const directUrls = Array.isArray(options.directUrls) ? options.directUrls : [];

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
            // Return minimal fallback with forced-path stubs rather than hard block.
            // Signal detection can still classify slugs from FORCED_PATHS.
            return buildFallbackResult(targetUrl, 'Homepage returned empty body.');
        }
        // Check for firewall/captcha on homepage itself
        if (isBlockedPage(body)) {
            console.warn(`[scraper] Homepage blocked by firewall — ${targetUrl}`);
            return buildFallbackResult(targetUrl, 'Homepage blocked by firewall or CAPTCHA.');
        }
        homepageHtml = body;
    } catch (err) {
        if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
            console.warn(`[scraper] Homepage fetch timed out (15s) — ${targetUrl}`);
        } else {
            console.warn(`[scraper] Homepage fetch failed (${err.code || err.message}) — ${targetUrl}`);
        }
        return buildFallbackResult(targetUrl, 'Homepage could not be fetched.');
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
    // Step 3b: Fetch user-supplied direct URLs (before FORCED_PATHS)
    // ----------------------------------------------------------------
    // These are governance page URLs submitted via the form when the company's
    // site blocks automated access. They are fetched unconditionally — the
    // redirect-wall duplicate-length check is intentionally skipped because the
    // user explicitly chose these URLs. A lower minimum body length (200 chars)
    // applies so that concise policy pages are not dropped.
    if (directUrls.length > 0) {
        console.log(`[scraper] Fetching ${directUrls.length} user-supplied direct URL(s)`);
        for (const directUrl of directUrls) {
            try {
                const dresp = await axios.get(directUrl, {
                    timeout: 10000,
                    headers: { 'User-Agent': USER_AGENT },
                    validateStatus: () => true,
                    maxRedirects: 5,
                });
                const dHtml = dresp.data ? String(dresp.data) : '';
                if (BLOCK_STATUS_CODES.includes(dresp.status)) {
                    console.log(`[scraper] Direct URL HTTP ${dresp.status} — ${directUrl}`);
                    combinedText += `\n\n--- Content from ${directUrl} ---\n[page restricted — HTTP ${dresp.status}]\n`;
                } else if (isBlockedPage(dHtml)) {
                    console.log(`[scraper] Direct URL firewall/captcha — ${directUrl}`);
                    combinedText += `\n\n--- Content from ${directUrl} ---\n[page restricted — firewall]\n`;
                } else {
                    const dClean = extractText(dHtml);
                    if (dClean.length >= 200) {
                        combinedText += `\n\n--- Content from ${directUrl} ---\n\n` + dClean;
                        successfulPages.push(directUrl);
                        // Record length so redirect-wall detection doesn't later flag
                        // a coincidentally same-length FORCED_PATH page.
                        seenPageLengths.add(dClean.length);
                        console.log(`[scraper] Direct URL OK ${directUrl} (${dClean.length} chars)`);
                    } else {
                        console.log(`[scraper] Direct URL body too short (${dClean.length} chars) — ${directUrl}`);
                        combinedText += `\n\n--- Content from ${directUrl} ---\n[page empty]\n`;
                    }
                }
            } catch (dErr) {
                console.log(`[scraper] Direct URL fetch error (${dErr.code || dErr.message}) — ${directUrl}`);
                combinedText += `\n\n--- Content from ${directUrl} ---\n[page restricted — fetch error]\n`;
            }
        }
    }

    // ----------------------------------------------------------------
    // Step 4: Fetch each page and extract text
    // ----------------------------------------------------------------
    let combinedText      = '';
    const successfulPages = [];
    // Tracks clean-text lengths of pages already fetched.
    // Used to detect redirect/wall pages that return HTTP 200 but identical
    // content across different URLs (see redirect/wall detection below).
    const seenPageLengths  = new Set();
    // Count of pages detected as redirect walls — used to trigger supplementary
    // evidence when most forced governance paths are blocked.
    let redirectWallCount  = 0;

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
                // Add URL stub so signal detection can classify this slug
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — HTTP ${statusCode}]\n`;
                continue;
            }
            if (isBlockedPage(pageHtml)) {
                console.log(`[scraper] Skipped firewall/captcha — ${pageUrl}`);
                // Add URL stub so signal detection can classify this slug
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — firewall]\n`;
                continue;
            }
            if (pageHtml.trim().length < 300) {
                console.log(`[scraper] Skipped body too short — ${pageUrl}`);
                // Add URL stub — slug may still be meaningful even without body text
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page empty]\n`;
                continue;
            }

            const cleanText = extractText(pageHtml);

            // ── Redirect/wall detection ──────────────────────────────────────
            // Some sites return HTTP 200 with a generic shell page for every
            // protected URL — short "sign in" walls AND full-length marketing
            // shells (e.g. IBM returns its 5,701-char homepage for every
            // locale-prefixed governance path).  Both produce identical clean-text
            // lengths across completely different paths, which is the reliable
            // signal here.
            //
            // Detection: if this page's clean text length exactly matches a
            // previously seen page length, treat it as a redirect wall regardless
            // of size.  The only guard is cleanText.length > 0 to avoid false
            // positives on genuinely empty pages (caught earlier by the < 300
            // raw HTML check, but defensive here too).
            //
            // The previous < 2000 ceiling was intentional for short walls but
            // caused large marketing shells to pass through unchecked.  Removing
            // it is safe because legitimate sites very rarely serve two different
            // governance pages with exactly the same extracted text length, and
            // any false positive (a real page coincidentally matching a prior
            // length) would at worst drop one page from a run that already has
            // sufficient other content.
            //
            // We track lengths in a Set rather than full content hashes to keep
            // memory overhead low and avoid hashing 30 KB strings per page.
            const isLikelyRedirectWall = (
                seenPageLengths.has(cleanText.length) &&
                cleanText.length > 0
            );
            seenPageLengths.add(cleanText.length);

            if (isLikelyRedirectWall) {
                console.log(`[scraper] Skipped redirect/wall (duplicate length ${cleanText.length}) — ${pageUrl}`);
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — redirect wall]\n`;
                redirectWallCount++;
                continue;
            }
            // ── End redirect/wall detection ──────────────────────────────────

            // ── Low-value page filter ─────────────────────────────────────────
            // Pages on fraud, scam, opt-out, cookie paths rarely contain AI
            // governance content. Accept them only if they mention at least one
            // AI governance term — otherwise add as a URL stub only so the slug
            // contributes to signal detection without polluting OpenAI's context.
            const pageUrlLower = pageUrl.toLowerCase();
            const isLowValuePath = LOW_VALUE_PATH_PATTERNS.some(p => pageUrlLower.includes(p));
            if (isLowValuePath) {
                const cleanLower = cleanText.toLowerCase();
                const hasGovernanceTerm = AI_GOVERNANCE_TERMS.some(t => cleanLower.includes(t));
                if (!hasGovernanceTerm) {
                    console.log(`[scraper] Skipped low-value path (no AI governance terms) — ${pageUrl}`);
                    combinedText += `\n\n--- Content from ${pageUrl} ---\n[page low-value — no governance terms]\n`;
                    continue;
                }
            }
            // ── End low-value page filter ─────────────────────────────────────
            combinedText   += `\n\n--- Content from ${pageUrl} ---\n\n` + cleanText;
            successfulPages.push(pageUrl);
            console.log(`[scraper] OK ${pageUrl} (${cleanText.length} chars)`);

        } catch (err) {
            // Per-page errors: still add URL stub for signal detection
            if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
                console.log(`[scraper] Skipped timeout (10s) — ${pageUrl}`);
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — timeout]\n`;
            } else {
                console.log(`[scraper] Skipped fetch error (${err.code || err.message}) — ${pageUrl}`);
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — fetch error]\n`;
            }
        }
    }

    // ----------------------------------------------------------------
    // Step 5: Assess limited_access, content_empty, and truncate
    // ----------------------------------------------------------------
    const limitedAccess = combinedText.trim().length < LIMITED_ACCESS_THRESHOLD;

    // content_empty: total chars exceed the limited_access threshold (so the
    // old code would pass it as valid) but almost all of that text is scraper
    // stubs from blocked/restricted pages — not real governance content.
    // report-generator uses this flag to route the evaluation as partial
    // rather than valid, preventing a full uplift on stub-only text.
    const realContentChars = measureRealContent(combinedText);
    const contentEmpty     = !limitedAccess && realContentChars < REAL_CONTENT_THRESHOLD;

    if (limitedAccess) {
        console.warn(`[scraper] limited_access=true — total text under ${LIMITED_ACCESS_THRESHOLD} chars`);
    }
    if (contentEmpty) {
        console.warn(`[scraper] content_empty=true — only ${realContentChars} real chars despite ${combinedText.trim().length} total (rest are stubs)`);
    }

    if (combinedText.length > MAX_CHARS) {
        console.log(`[scraper] Truncating ${combinedText.length} chars to ${MAX_CHARS}`);
        combinedText = combinedText.slice(0, MAX_CHARS) + '... [TRUNCATED]';
    }

    console.log(`[scraper] Complete — ${successfulPages.length}/${uniquePages.length} pages OK, ${combinedText.length} total chars, ${realContentChars} real chars, ${redirectWallCount} redirect walls`);

    return {
        scraper_blocked:    false,
        combined_text:      combinedText,
        scraped_pages:      successfulPages,
        limited_access:     limitedAccess,
        content_empty:      contentEmpty,
        real_content_chars: realContentChars,
        redirect_wall_count: redirectWallCount,
    };
}


// ---------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------

function blocked(message) {
    return { scraper_blocked: true, message };
}

/**
 * buildFallbackResult — used when the homepage is unreachable but we can
 * still generate URL stubs for FORCED_PATHS. Signal detection in
 * report-generator reads these stubs to classify governance slugs.
 * Returns scraper_blocked: false with partial_scrape: true so evaluate.js
 * knows to treat this as a partial evaluation, not a full block.
 */
function buildFallbackResult(targetUrl, reason) {
    let parsedBase;
    try { parsedBase = new URL(targetUrl); } catch (_) { return blocked(reason); }
    const baseOrigin = parsedBase.origin;

    // Build stub text for all forced paths — even blocked ones are useful slugs
    let fallbackText = `[Fallback evaluation — ${reason}]\n`;
    fallbackText += `[Homepage: ${targetUrl}]\n`;
    for (const path of FORCED_PATHS) {
        fallbackText += `\n--- Content from ${baseOrigin + path} ---\n[page not retrieved]\n`;
    }

    console.log(`[scraper] buildFallbackResult — ${FORCED_PATHS.length} path stubs generated for ${targetUrl}`);
    return {
        scraper_blocked: false,
        partial_scrape:  true,
        combined_text:   fallbackText,
        scraped_pages:   [],
        limited_access:  true,
        message:         reason
    };
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
