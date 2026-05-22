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
    // Foundational governance methodology vocabulary — enables semantic
    // link discovery for governance-focused organisations that publish
    // methodology, scoring frameworks, and accountability architecture
    // on pages with non-standard URL slugs.
    'scoring methodology', 'governance architecture', 'accountability architecture',
    'certification methodology', 'human alignment', 'trust framework',
    'evidence-based', 'governance framework', 'alignment scoring',
    'governance taxonomy', 'responsible deployment', 'ethical infrastructure',
    'evaluation framework', 'governance playbook', 'measurable standards',
    'independent accountability', 'alignment framework',
];

const FORCED_PATHS = [
    // ── High-specificity AI governance paths — fetched first to ensure
    //    they land inside the MAX_CHARS window before lower-value pages
    //    (e.g. /privacy at 39K chars) consume the budget.
    // ── 0. Governance methodology paths — HIGHEST PRIORITY ───────────────────
    // These paths are fetched FIRST because governance-focused organisations
    // (e.g. Humaital) publish their methodology at product-specific slugs that
    // would otherwise be reached after the 10-page cap fires on ghost paths.
    // Placing them first guarantees they are attempted before any locale-prefixed
    // enterprise paths that return empty shells on non-enterprise sites.
    '/rating-scoring',
    '/rating-scoring/',
    '/how-it-works',
    '/our-methodology',
    '/about/scoring',
    '/about/rating',
    // ── 1. AI-specific governance paths — highest priority ───────────────────
    // Fetched first so their content lands inside the 15,000-char OpenAI window
    // before broad corporate pages (sustainability, about) consume the budget.
    // Locale-prefixed variants for large enterprises (Microsoft, Google, etc.)
    // are included here because they carry the richest AI governance content.
    '/en-us/ai/responsible-ai',
    '/en-us/ai/principles-and-approach',
    '/en-gb/ai/responsible-ai',
    '/en/responsible-ai',
    '/en/ai-governance',
    '/en-us/trust-center',
    '/en-us/about/responsible-ai',
    '/en-us/corporate-responsibility',
    '/responsible-ai',
    '/ai-governance',
    '/ai-policy',
    '/ethics',
    '/trust',
    // IBM-specific — tactical addition; IBM's primary governance content is not
    // at standard paths.  Long-term fix is semantic homepage link discovery.
    // Direct URL submission (options.directUrls) is the preferred user-facing
    // workaround for IBM and similar enterprise sites.
    '/impact',
    '/topics/ai-ethics',
    // ── 2. Risk / compliance / governance pages ───────────────────────────────
    '/risk', '/compliance', '/regulatory', '/governance',
    // ── 3. Broad corporate responsibility pages ───────────────────────────────
    // Placed after AI governance paths so they are truncated by the 15K OpenAI
    // trim rather than crowding out governance content.
    '/corporate-responsibility', '/responsibility', '/esg', '/sustainability',
    // ── 4. Generic pages — lowest priority ───────────────────────────────────
    // Useful for signal detection but should not consume governance content budget.
    '/about', '/about-us',
    '/ai', '/artificial-intelligence', '/technology',
    '/investor-relations', '/newsroom', '/public-policy',
    '/privacy', '/terms',
];

// ── Foundational governance methodology paths ────────────────────────────────
// These paths are specific to governance-focused emerging organisations and
// reliably 404 or slow-redirect on enterprise sites, consuming wall-clock budget
// before genuine enterprise governance paths complete.
//
// They are NOT included in FORCED_PATHS. Instead they are attempted in a
// conditional post-loop pass (see Step 4b in scrapeCompanyPages) only when:
//   - at least 8 seconds of the overall budget remain, AND
//   - the confirmed-page cap has not been reached.
// Each foundational path uses a reduced 3-second timeout (vs 6s for main paths)
// so that enterprise CDN slow-timeouts fail fast rather than consuming budget.
//
// buildFallbackResult intentionally uses only FORCED_PATHS for stub generation —
// foundational stubs in a fallback run add no signal value and pollute the
// fallback text unnecessarily.
const FOUNDATIONAL_PATHS = [
    '/methodology',
    '/scoring',
    '/framework',
    '/certification',
    '/governance-framework',
    '/trust-framework',
    '/accountability-framework',
    '/alignment',
    '/responsible-deployment',
    '/about/methodology',
    '/about/governance',
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
    // Foundational governance methodology terms — ensures pages containing
    // evaluation frameworks, scoring systems, and accountability architecture
    // are not discarded by the low-value page filter.
    'scoring methodology', 'certification methodology', 'governance architecture',
    'human alignment', 'evidence-based scoring', 'trust framework',
    'evaluation framework', 'alignment scoring', 'governance taxonomy',
];

// High-value governance URL slugs that are EXEMPT from redirect-wall detection.
// A false positive on these slugs (dropping a real governance page) is a more
// serious error than a false negative (passing a redirect wall through to GPT-4o,
// which simply assigns level 1 to unrecognised content — the same result as a stub).
// Pages whose URL contains any of these terms bypass the fingerprint-duplicate check.
// Their fingerprint is still recorded so subsequent non-governance pages can be
// compared against it.
const GOVERNANCE_EXEMPT_SLUGS = [
    'responsible-ai', 'ai-principles', 'principles-and-approach',
    'ai-governance',  'ai-ethics',     'ethical-ai',
    'ai-safety',      'ai-policy',     'human-alignment',
    'trustworthy-ai', 'responsible-technology', 'trust-center',
    'rating-scoring', 'how-it-works',  'our-methodology',
];

const BLOCK_KEYWORDS = [
    'Just a moment...', 'Cloudflare', 'Access Denied',
    'Security challenge', 'Please enable JS', 'enable JavaScript',
    'Not Acceptable', 'Attention Required!', 'Pardon Our Interruption'
];

const BLOCK_STATUS_CODES    = [403, 406, 429, 503];
const MAX_DISCOVERED_LINKS  = 5;
const MAX_CHARS             = 30000;
// Per-page contribution cap: limits how many chars a single page can add to
// combinedText before the global MAX_CHARS truncation.  Without this, one
// large page (e.g. a 39,313-char privacy policy) can consume the entire
// window, causing high-value governance pages fetched later to be truncated
// out entirely.  5,000 chars preserves substantive governance content from
// AI ethics, trust, and responsibility pages while preventing runaway budget
// consumption from boilerplate-heavy pages like privacy policies and terms.
const MAX_PAGE_CHARS        = 5000;
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
    // Timeout increased to 25s (from 15s): large enterprise sites served
    // through global CDNs can add latency from Railway's network environment
    // that exceeds 15s, causing systematic fallback-mode evaluations with
    // zero real content (raw_score=0, score=calibration floor only).
    //
    // One retry on timeout/network failure: CDN latency spikes are often
    // transient. A single retry with a 2s delay recovers most cases without
    // meaningfully increasing evaluation time for sites that do succeed on
    // the first attempt.  Retry is NOT attempted for firewall/captcha blocks
    // or empty bodies — those are deterministic failures, not transient ones.
    let homepageHtml;
    let homepageFetchError = null;

    for (let _attempt = 1; _attempt <= 2; _attempt++) {
        homepageFetchError = null;
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
                // Empty body is deterministic — do not retry.
                return buildFallbackResult(targetUrl, 'Homepage returned empty body.');
            }
            // Firewall/captcha is deterministic — do not retry.
            if (isBlockedPage(body)) {
                console.warn(`[scraper] Homepage blocked by firewall — ${targetUrl}`);
                return buildFallbackResult(targetUrl, 'Homepage blocked by firewall or CAPTCHA.');
            }
            homepageHtml = body;
            break; // Success — exit retry loop
        } catch (err) {
            const isTimeout = err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT';
            const isNetwork = !isTimeout; // covers ECONNREFUSED, ENOTFOUND, etc.

            if (_attempt === 1 && (isTimeout || isNetwork)) {
                // Transient failure — retry once after a short delay
                const reason = isTimeout ? `timed out (25s)` : `failed (${err.code || err.message})`;
                console.warn(`[scraper] Homepage fetch ${reason} — ${targetUrl}`);
                console.log(`[scraper] Homepage fetch retry 1/1 — waiting 2s before retry`);
                await new Promise(resolve => setTimeout(resolve, 2000));
                continue;
            }
            // Second attempt failed — record error and fall through to fallback
            homepageFetchError = err;
        }
    }

    if (!homepageHtml) {
        const err = homepageFetchError;
        const isTimeout = err && (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT');
        console.warn(`[scraper] Homepage fetch failed after retry — ${targetUrl}` +
                     (err ? ` (${err.code || err.message})` : ''));
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
    // Priority order: FORCED_PATHS first, then homepage, then discovered links.
    //
    // Rationale: combinedText is truncated to MAX_CHARS after all pages are
    // concatenated. With the homepage first, a large page (e.g. IBM's privacy
    // page at 39,313 chars) consumes most of the budget before governance-
    // specific paths are appended — causing high-value content like
    // /topics/ai-ethics (21,522 chars) to be truncated out entirely.
    //
    // Placing FORCED_PATHS first ensures governance-specific paths land inside
    // the OpenAI window. The homepage moves to second position and is still
    // fetched for signal detection and discovered-link context.
    const pagesToScrape = [];

    for (const path of FORCED_PATHS) {
        pagesToScrape.push(baseOrigin + path);
    }

    // Homepage after FORCED_PATHS — deprioritised in concatenation order
    // but still included for signal detection and as a fallback.
    if (!pagesToScrape.includes(targetUrl)) {
        pagesToScrape.push(targetUrl);
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
                    timeout: 6000,
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
                        // Record fingerprint so redirect-wall detection doesn't later flag
                        // a coincidentally similar FORCED_PATH page.
                        const _dFp = dClean.slice(50, 200).toLowerCase().replace(/\s+/g, ' ');
                        seenPageFingerprints.add(_dFp);
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
    // ── Overall scrape budget ─────────────────────────────────────────────────
    // Prevents large-company scrapes (e.g. Microsoft) from timing out the API.
    // 50 seconds total wall-clock budget (increased from 40s to provide headroom
    // for the conditional foundational-path pass that runs after the main loop).
    // If hit, we return whatever confirmed evidence has been collected so far
    // as a partial_scrape result.
    const OVERALL_BUDGET_MS    = 50000;
    const CONFIRMED_PAGE_CAP   = 10;   // stop after this many pages with real content
    const _scrapeStart         = Date.now();
    let   _budgetReached       = false;
    let   _pageCapReached      = false;
    // ── End overall scrape budget ─────────────────────────────────────────────

    let combinedText      = '';
    const successfulPages = [];
    // All URLs we attempted, regardless of outcome.
    // Returned so the frontend appendix can label unconfirmed paths as
    // "Attempted source / no evidence found" rather than "Page scanned".
    const attemptedPaths  = [];
    // Tracks content fingerprints of pages already fetched.
    // Used to detect redirect/wall pages that return HTTP 200 but identical
    // content across different URLs (see redirect/wall detection below).
    //
    // Fingerprint = chars 50–200 of cleaned text, lowercased, whitespace-normalised.
    // Skipping the first 50 chars avoids triggering on shared navigation chrome
    // (e.g. "Skip to main content") that many enterprise pages share at the very
    // beginning. Characters 50–200 reliably reach the first body-specific content.
    //
    // This replaces the previous cleanText.length approach, which produced false
    // positives on enterprise sites where two genuine governance pages happen to
    // produce the same total character count after HTML stripping (e.g. Google's
    // locale-prefixed AI governance pages share heavy navigation/footer chrome).
    const seenPageFingerprints = new Set();
    // Count of pages detected as redirect walls — used to trigger supplementary
    // evidence when most forced governance paths are blocked.
    let redirectWallCount  = 0;

    for (const pageUrl of uniquePages) {
        // ── Overall budget check ───────────────────────────────────────────────
        if (Date.now() - _scrapeStart > OVERALL_BUDGET_MS) {
            _budgetReached = true;
            console.log(`[scraper] Overall scrape budget reached (40s) after ${successfulPages.length} confirmed pages — returning partial result`);
            break;
        }
        // ── Confirmed-page cap check ───────────────────────────────────────────
        if (successfulPages.length >= CONFIRMED_PAGE_CAP) {
            _pageCapReached = true;
            console.log(`[scraper] Evidence page target reached (${CONFIRMED_PAGE_CAP} confirmed pages) — stopping early`);
            break;
        }
        // ── MAX_CHARS early exit ───────────────────────────────────────────────
        if (combinedText.length >= MAX_CHARS) {
            console.log(`[scraper] MAX_CHARS reached mid-loop — stopping early`);
            break;
        }
        attemptedPaths.push(pageUrl); // record every URL tried
        try {
            const resp = await axios.get(pageUrl, {
                timeout: 6000,
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

            // ── Minimum clean text threshold ──────────────────────────────────
            // WordPress sites that return a redirect-to-homepage for unknown paths
            // serve the full nav + footer chrome but NO page body content. After
            // extractText() strips HTML tags, these pages return ~1,156 chars of
            // navigation and footer text — enough to pass the 300-char raw HTML
            // check but containing zero governance content.
            //
            // Threshold raised to 1,500 chars to reject these ghost pages.
            // 1,156 chars = WordPress ghost page (nav + footer only)
            // 1,500+ chars = any page with at least minimal body content
            // Real governance pages return 2,000–30,000 chars after extraction.
            // URL stub is still written so signal detection works on the slug.
            if (cleanText.trim().length < 1500) {
                console.log(`[scraper] Skipped thin content (${cleanText.length} clean chars) — ${pageUrl}`);
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — thin content]\n`;
                continue;
            }
            // ── End minimum clean text threshold ─────────────────────────────

            // ── Redirect/wall detection ──────────────────────────────────────
            // Some sites return HTTP 200 with a generic shell page for every
            // protected URL — short sign-in walls AND full-length marketing
            // shells (e.g. IBM returns its homepage for every locale-prefixed
            // governance path). Both produce identical content across different
            // paths, which is the reliable detection signal.
            //
            // Detection method: content fingerprint (chars 50–200 of cleaned text,
            // lowercased, whitespace-normalised). Skipping the first 50 chars avoids
            // false positives from shared navigation chrome ("Skip to main content").
            // Characters 50–200 reliably reach the first body-specific content.
            //
            // This replaces the previous cleanText.length approach which caused false
            // positives on enterprise sites where two genuine governance pages produce
            // the same total character count after HTML stripping (e.g. Google's
            // locale-prefixed AI governance pages sharing heavy nav/footer chrome).
            //
            // Governance-exempt bypass: pages whose URL contains a known high-value
            // governance slug are never dropped as redirect walls. A false positive
            // on /en-us/ai/responsible-ai is a more serious error than a false
            // negative (a shell page reaching GPT-4o, which assigns level 1 —
            // the same result as a stub). The fingerprint is still recorded so
            // subsequent non-governance pages can be compared against it.
            const pageUrlLowerForWall = pageUrl.toLowerCase();
            const isGovernanceExempt  = GOVERNANCE_EXEMPT_SLUGS.some(slug =>
                pageUrlLowerForWall.includes(slug)
            );

            const fingerprint = cleanText.slice(50, 200).toLowerCase().replace(/\s+/g, ' ');
            const isLikelyRedirectWall = (
                !isGovernanceExempt &&
                fingerprint.length > 0 &&
                seenPageFingerprints.has(fingerprint)
            );
            // Always record the fingerprint — even exempt pages contribute to the
            // seen-fingerprint set so subsequent non-exempt pages can be checked.
            seenPageFingerprints.add(fingerprint);

            if (isLikelyRedirectWall) {
                console.log(`[scraper] Skipped redirect/wall (duplicate fingerprint, len=${cleanText.length}) — ${pageUrl}`);
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
            const isLowValuePath = LOW_VALUE_PATH_PATTERNS.some(p => pageUrlLowerForWall.includes(p));
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

            // ── Per-page contribution cap ─────────────────────────────────────
            // Prevents a single large page from consuming the entire MAX_CHARS
            // budget.  The most common offender is the /privacy page which can
            // exceed 39,000 chars of legal boilerplate.  Capping at MAX_PAGE_CHARS
            // preserves budget for governance-specific pages fetched later.
            // The URL stub is always written so signal detection still works.
            const cappedText = cleanText.length > MAX_PAGE_CHARS
                ? cleanText.slice(0, MAX_PAGE_CHARS) + '... [page capped]'
                : cleanText;
            if (cleanText.length > MAX_PAGE_CHARS) {
                console.log(`[scraper] Capped ${cleanText.length} → ${MAX_PAGE_CHARS} chars — ${pageUrl}`);
            }
            // ── End per-page contribution cap ─────────────────────────────────

            combinedText   += `\n\n--- Content from ${pageUrl} ---\n\n` + cappedText;
            successfulPages.push(pageUrl);
            console.log(`[scraper] OK ${pageUrl} (${cleanText.length} chars)`);

        } catch (err) {
            // Per-page errors: still add URL stub for signal detection
            if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
                console.log(`[scraper] Skipped timeout (6s) — ${pageUrl}`);
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — timeout]\n`;
            } else {
                console.log(`[scraper] Skipped fetch error (${err.code || err.message}) — ${pageUrl}`);
                combinedText += `\n\n--- Content from ${pageUrl} ---\n[page restricted — fetch error]\n`;
            }
        }
    }

    // ----------------------------------------------------------------
    // Step 4b: Conditional foundational-path pass
    // ----------------------------------------------------------------
    // FOUNDATIONAL_PATHS are startup-oriented slugs (/methodology, /scoring,
    // /framework, etc.) that reliably 404 or slow-redirect on enterprise sites,
    // consuming wall-clock budget before genuine enterprise governance paths
    // complete when placed in the main FORCED_PATHS queue unconditionally.
    //
    // They are attempted here — after the main loop — only when:
    //   1. At least 8 seconds of the overall budget remain (prevents foundational
    //      paths from causing the total scrape to exceed the budget envelope).
    //   2. The confirmed-page cap has not been reached (no additional pages needed).
    //   3. The MAX_CHARS budget has not been exhausted.
    //
    // Each path uses a 3-second timeout (vs 6s for main paths) so that enterprise
    // CDN slow-timeouts fail fast rather than consuming budget. Startup sites that
    // actually have these pages respond well within 3 seconds.
    //
    // The redirect-wall fingerprint check and governance-exempt bypass apply
    // exactly as in the main loop.
    const _foundationalBudgetRemaining = OVERALL_BUDGET_MS - (Date.now() - _scrapeStart);
    const _foundationalCanRun = (
        _foundationalBudgetRemaining >= 8000 &&
        successfulPages.length < CONFIRMED_PAGE_CAP &&
        combinedText.length < MAX_CHARS
    );

    if (_foundationalCanRun) {
        console.log(`[scraper] Foundational path pass — ${_foundationalBudgetRemaining}ms remaining, attempting ${FOUNDATIONAL_PATHS.length} paths`);
        for (const fPath of FOUNDATIONAL_PATHS) {
            // Re-check budget and cap on each iteration
            if (Date.now() - _scrapeStart > OVERALL_BUDGET_MS - 1000) {
                console.log(`[scraper] Foundational pass budget exhausted — stopping`);
                break;
            }
            if (successfulPages.length >= CONFIRMED_PAGE_CAP) break;
            if (combinedText.length >= MAX_CHARS) break;

            const fPageUrl = baseOrigin + fPath;
            if (uniquePages.includes(fPageUrl)) continue; // already attempted in main loop

            attemptedPaths.push(fPageUrl);
            try {
                const fResp = await axios.get(fPageUrl, {
                    timeout: 3000,   // reduced timeout — fail fast on enterprise CDN stalls
                    headers: { 'User-Agent': USER_AGENT },
                    validateStatus: () => true,
                    maxRedirects: 3
                });

                const fStatus = fResp.status;
                const fHtml   = fResp.data ? String(fResp.data) : '';

                if (BLOCK_STATUS_CODES.includes(fStatus)) {
                    combinedText += `\n\n--- Content from ${fPageUrl} ---\n[page restricted — HTTP ${fStatus}]\n`;
                    continue;
                }
                if (isBlockedPage(fHtml)) {
                    combinedText += `\n\n--- Content from ${fPageUrl} ---\n[page restricted — firewall]\n`;
                    continue;
                }
                if (fHtml.trim().length < 300) {
                    combinedText += `\n\n--- Content from ${fPageUrl} ---\n[page empty]\n`;
                    continue;
                }

                const fClean = extractText(fHtml);

                // Apply same thin content check as main loop
                if (fClean.trim().length < 1500) {
                    console.log(`[scraper] Foundational thin content (${fClean.length} chars) — ${fPageUrl}`);
                    combinedText += `\n\n--- Content from ${fPageUrl} ---\n[page restricted — thin content]\n`;
                    continue;
                }

                // Redirect-wall fingerprint check (same logic as main loop)
                const fUrlLower    = fPageUrl.toLowerCase();
                const fIsExempt    = GOVERNANCE_EXEMPT_SLUGS.some(slug => fUrlLower.includes(slug));
                const fFingerprint = fClean.slice(50, 200).toLowerCase().replace(/\s+/g, ' ');
                const fIsWall      = !fIsExempt && fFingerprint.length > 0 && seenPageFingerprints.has(fFingerprint);
                seenPageFingerprints.add(fFingerprint);

                if (fIsWall) {
                    console.log(`[scraper] Foundational skipped redirect/wall — ${fPageUrl}`);
                    combinedText += `\n\n--- Content from ${fPageUrl} ---\n[page restricted — redirect wall]\n`;
                    redirectWallCount++;
                    continue;
                }

                const fCapped = fClean.length > MAX_PAGE_CHARS
                    ? fClean.slice(0, MAX_PAGE_CHARS) + '... [page capped]'
                    : fClean;

                combinedText += `\n\n--- Content from ${fPageUrl} ---\n\n` + fCapped;
                successfulPages.push(fPageUrl);
                console.log(`[scraper] Foundational OK ${fPageUrl} (${fClean.length} chars)`);

            } catch (fErr) {
                if (fErr.code === 'ECONNABORTED' || fErr.code === 'ETIMEDOUT') {
                    console.log(`[scraper] Foundational timeout (3s) — ${fPageUrl}`);
                } else {
                    console.log(`[scraper] Foundational fetch error (${fErr.code || fErr.message}) — ${fPageUrl}`);
                }
                combinedText += `\n\n--- Content from ${fPageUrl} ---\n[page restricted — timeout]\n`;
            }
        }
        console.log(`[scraper] Foundational pass complete — ${successfulPages.length} total confirmed pages`);
    } else {
        console.log(`[scraper] Foundational pass skipped — budget=${_foundationalBudgetRemaining}ms pages=${successfulPages.length}/${CONFIRMED_PAGE_CAP} chars=${combinedText.length}/${MAX_CHARS}`);
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

    // partial_scrape is true when the budget or page cap cut the loop short,
    // or when content was too limited to assess fully.
    const partialScrape = _budgetReached || _pageCapReached ||
                          limitedAccess  || contentEmpty;

    return {
        scraper_blocked:    false,
        partial_scrape:     partialScrape,
        combined_text:      combinedText,
        scraped_pages:      successfulPages,
        // All URLs tried — includes both successful pages and failed/blocked attempts.
        // The frontend appendix should label entries NOT in scraped_pages as
        // "Attempted source / no evidence found" rather than "Evidence identified".
        attempted_paths:    attemptedPaths,
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

    const fallbackAttempted = FORCED_PATHS.map(p => baseOrigin + p);
    console.log(`[scraper] buildFallbackResult — ${FORCED_PATHS.length} path stubs generated for ${targetUrl}`);
    return {
        scraper_blocked: false,
        partial_scrape:  true,
        combined_text:   fallbackText,
        scraped_pages:   [],
        attempted_paths: fallbackAttempted,
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
