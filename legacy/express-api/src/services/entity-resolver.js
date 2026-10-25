// ============================================================
// FIX 11 — ENTITY RESOLUTION
// FILE:  src/services/entity-resolver.js  (new file)
//        src/routes/evaluate.js           (integration — Step 0)
//        bundle.js                        (frontend entity card)
//
// DESIGN PRINCIPLES:
//   Entity resolution improves the accuracy of evidence queries.
//   It is not a gatekeeping mechanism — it is a data quality layer.
//
//   Wikidata is one identity signal among several. It is useful,
//   broadly accurate, and freely available. It is also community-
//   maintained, occasionally out of date, and absent for many
//   non-public organisations. It is treated as a first-pass
//   signal, not the final authority on identity.
//
//   The resolution pipeline:
//     1. Wikidata — provides candidate canonical name and official domain
//     2. EDGAR CIK — cross-checks public company registration independently
//     3. Domain comparison — compares submitted URL against known official domain
//     4. Confidence scoring — three signals combined, none individually decisive
//
//   When Wikidata and EDGAR agree: high confidence.
//   When only one matches: moderate confidence; warning surfaced.
//   When neither matches: low confidence; assessment proceeds with
//     submitted name and URL, with a disclosure note in the output.
//
//   The resolved name is used for downstream EDGAR, NIST, ISO queries.
//   The submitted name is always preserved and shown in the output.
//   The user's input is never silently overridden without disclosure.
// ============================================================

const axios = require('axios');


// ══════════════════════════════════════════════════════════════
// SECTION 1: WIKIDATA LOOKUP
// Returns candidate entity data including official website,
// CIK, LEI, and industry classification.
// Used as one signal — not the final authority.
// ══════════════════════════════════════════════════════════════

async function lookupWikidata(companyName) {
    try {
        const searchUrl = `https://www.wikidata.org/w/api.php?action=wbsearchentities` +
            `&search=${encodeURIComponent(companyName)}&language=en&type=item&limit=5&format=json`;

        const searchRes = await axios.get(searchUrl, {
            timeout: 6000,
            headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
        });

        // Filter to candidates that describe organisations
        const ORG_TERMS = ['company', 'corporation', 'organisation', 'organization',
                           'agency', 'enterprise', 'firm', 'government', 'department'];
        const candidates = (searchRes.data?.search || []).filter(item =>
            item.description && ORG_TERMS.some(t => item.description.toLowerCase().includes(t))
        );

        if (candidates.length === 0) return null;

        const topMatch = candidates[0];
        const entityUrl = `https://www.wikidata.org/w/api.php?action=wbgetentities` +
            `&ids=${topMatch.id}&props=claims|labels|descriptions&languages=en&format=json`;

        const entityRes = await axios.get(entityUrl, {
            timeout: 6000,
            headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
        });

        const entity = entityRes.data?.entities?.[topMatch.id];
        if (!entity) return null;

        const claims = entity.claims || {};

        // Extract single-value property
        const extractSingleValue = (propId) => {
            const claim = claims[propId];
            if (!claim || !claim[0]) return null;
            return claim[0].mainsnak?.datavalue?.value;
        };

        // Extract string property (URL, identifier)
        const extractString = (propId) => {
            const val = extractSingleValue(propId);
            return typeof val === 'string' ? val : null;
        };

        // P856 = official website, P1566 = CIK (SEC), P1278 = LEI,
        // P452 = industry (may be a Wikidata item reference), P1128 = employees
        const officialWebsite    = extractString('P856');
        const cik                = extractString('P1566');
        const lei                = extractString('P1278');
        const resolvedName       = entity.labels?.en?.value || topMatch.label || companyName;
        const wikidataId         = topMatch.id;

        // Industry: P452 may be a Wikidata item ID, not a plain string
        const industryRaw = extractSingleValue('P452');
        const resolvedIndustry = (typeof industryRaw === 'string')
            ? industryRaw
            : (industryRaw && industryRaw.id) ? industryRaw.id : null;

        // Name similarity between input and Wikidata resolved name
        const matchScore = computeNameMatchScore(companyName, resolvedName);

        return {
            wikidataId,
            resolvedName,
            officialWebsite,
            cik,
            lei,
            resolvedIndustry,
            matchScore,
            source: 'wikidata'
        };
    } catch (err) {
        // Wikidata unavailable or no match — not a blocking failure
        console.log('[HAI] Wikidata lookup failed:', err.message);
        return null;
    }
}


// ══════════════════════════════════════════════════════════════
// SECTION 2: EDGAR CIK RESOLUTION
// Independent cross-check: query SEC EDGAR by company name,
// extract CIK for use in all downstream EDGAR queries.
// Failure is non-blocking.
// ══════════════════════════════════════════════════════════════

async function resolveEdgarCik(companyName) {
    try {
        const url = `https://efts.sec.gov/LATEST/search-index?q=%22${encodeURIComponent(companyName)}%22&dateRange=custom&startdt=2020-01-01&forms=10-K`;

        const res = await axios.get(url, {
            timeout: 7000,
            headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
        });

        const hits = res.data?.hits?.hits || [];
        if (hits.length === 0) return null;

        const top = hits[0]._source || {};
        return {
            cik:         top.entity_id  || null,
            filedName:   top.display_names?.[0] || top.entity_name || null,
            formType:    top.form_type  || null,
            filingDate:  top.file_date  || null,
            source:      'edgar'
        };
    } catch (err) {
        console.log('[HAI] EDGAR CIK resolution failed:', err.message);
        return null;
    }
}


// ══════════════════════════════════════════════════════════════
// SECTION 3: DOMAIN VERIFICATION
// Compares submitted URL domain against Wikidata official website.
// Returns a match result and confidence, not a pass/fail.
// ══════════════════════════════════════════════════════════════

function extractDomain(url) {
    if (!url) return null;
    try {
        const u = new URL(url.startsWith('http') ? url : 'https://' + url);
        // Return second-level domain (e.g. "microsoft" from "microsoft.com")
        const parts = u.hostname.replace(/^www\./, '').split('.');
        return parts.length >= 2 ? parts.slice(-2).join('.') : u.hostname;
    } catch {
        return null;
    }
}

function verifyDomainMatch(submittedUrl, officialWebsite) {
    const submitted = extractDomain(submittedUrl);
    const official  = extractDomain(officialWebsite);

    if (!submitted || !official) {
        return { match: null, confidence: 0.5, reason: 'Domain comparison not possible — one or both URLs missing' };
    }
    if (submitted === official) {
        return { match: true, confidence: 1.0, reason: 'Exact domain match' };
    }
    // Partial match: one is a subdomain or variant of the other
    if (submitted.includes(official) || official.includes(submitted)) {
        return { match: true, confidence: 0.85, reason: 'Domain variant match' };
    }
    return {
        match: false,
        confidence: 0.2,
        reason: `Domain mismatch: submitted domain (${submitted}) does not match official domain (${official})`
    };
}


// ══════════════════════════════════════════════════════════════
// SECTION 4: NAME MATCH SCORING
// Simple normalised string similarity.
// Returns 0.0–1.0.
// ══════════════════════════════════════════════════════════════

function computeNameMatchScore(inputName, resolvedName) {
    if (!inputName || !resolvedName) return 0;
    const a = inputName.toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
    const b = resolvedName.toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
    if (a === b) return 1.0;
    if (b.includes(a) || a.includes(b)) return 0.9;

    // Token overlap (Jaccard similarity on word tokens)
    const setA = new Set(a.split(/\s+/));
    const setB = new Set(b.split(/\s+/));
    const intersection = [...setA].filter(t => setB.has(t)).length;
    const union = new Set([...setA, ...setB]).size;
    return union === 0 ? 0 : Math.round((intersection / union) * 100) / 100;
}


// ══════════════════════════════════════════════════════════════
// SECTION 5: OVERALL ENTITY CONFIDENCE
// Combines three signals: Wikidata name match, domain match,
// EDGAR cross-check. No single signal is decisive.
// ══════════════════════════════════════════════════════════════

function computeEntityConfidence(nameMatchScore, domainMatchConfidence, hasEdgarCrossCheck) {
    let score = 0;
    // Wikidata name match: up to 0.35
    if (nameMatchScore >= 0.9)       score += 0.35;
    else if (nameMatchScore >= 0.7)  score += 0.20;
    else if (nameMatchScore >= 0.5)  score += 0.10;
    // Domain match: up to 0.40
    if (domainMatchConfidence >= 0.9)      score += 0.40;
    else if (domainMatchConfidence >= 0.7) score += 0.25;
    else if (domainMatchConfidence >= 0.4) score += 0.10;
    // EDGAR independent cross-check: up to 0.25
    if (hasEdgarCrossCheck) score += 0.25;

    return Math.min(1.0, Math.round(score * 100) / 100);
}


// ══════════════════════════════════════════════════════════════
// SECTION 6: resolveEntity() — MAIN ORCHESTRATION FUNCTION
// Call from evaluate.js as Step 0, before scraping.
// Returns entityProfile. Never throws — all lookups fail gracefully.
// ══════════════════════════════════════════════════════════════

async function resolveEntity(companyName, submittedUrl) {
    const warnings = [];

    // Run Wikidata and EDGAR in parallel — both may fail independently
    const [wikidataResult, edgarResult] = await Promise.all([
        lookupWikidata(companyName).catch(() => null),
        resolveEdgarCik(companyName).catch(() => null)
    ]);

    // Domain verification against Wikidata official website (if available)
    const domainCheck = wikidataResult?.officialWebsite
        ? verifyDomainMatch(submittedUrl, wikidataResult.officialWebsite)
        : { match: null, confidence: 0.5, reason: 'No official website found in Wikidata for this entity' };

    // Name match
    const nameMatchScore = wikidataResult
        ? computeNameMatchScore(companyName, wikidataResult.resolvedName)
        : 0;

    // Build warnings — informational, not blocking
    if (domainCheck.match === false) {
        warnings.push(
            `The submitted URL domain does not match the domain on record for "${wikidataResult?.resolvedName}" ` +
            `in Wikidata. Evidence queries will use the resolved entity name. ` +
            `If this is a subsidiary or regional site, this may be expected.`
        );
    }

    if (nameMatchScore < 0.6 && wikidataResult) {
        warnings.push(
            `The submitted company name ("${companyName}") has a low similarity score to ` +
            `the Wikidata entity name ("${wikidataResult.resolvedName}"). ` +
            `This may indicate a different entity, a trade name, or a naming variation. ` +
            `EDGAR queries will use the Wikidata resolved name; results should be verified.`
        );
    }

    if (!wikidataResult && !edgarResult) {
        warnings.push(
            `No entity record was found in Wikidata or EDGAR for "${companyName}". ` +
            `This is common for private companies, subsidiaries, and government agencies. ` +
            `Evidence queries will use the submitted name and URL directly.`
        );
    }

    // EDGAR name cross-check: if EDGAR filed name differs substantially from Wikidata name
    if (edgarResult && wikidataResult && edgarResult.filedName) {
        const edgarNameMatch = computeNameMatchScore(wikidataResult.resolvedName, edgarResult.filedName);
        if (edgarNameMatch < 0.5) {
            warnings.push(
                `The EDGAR filing name ("${edgarResult.filedName}") differs significantly from ` +
                `the Wikidata resolved name ("${wikidataResult.resolvedName}"). ` +
                `The EDGAR CIK will be used for SEC queries; human review is recommended.`
            );
        }
    }

    // Resolved name: prefer Wikidata if high-confidence match; otherwise use submitted name
    const resolvedName = (wikidataResult && nameMatchScore >= 0.6)
        ? wikidataResult.resolvedName
        : companyName;

    // CIK: prefer EDGAR direct lookup; fall back to Wikidata CIK
    const resolvedCik = edgarResult?.cik || wikidataResult?.cik || null;

    const overallConfidence = computeEntityConfidence(
        nameMatchScore,
        domainCheck.confidence,
        !!edgarResult
    );

    const entityProfile = {
        // Input preservation — user's submission is never silently replaced
        inputName:           companyName,
        inputUrl:            submittedUrl,

        // Resolution results
        resolvedName,
        resolvedDomain:      wikidataResult?.officialWebsite
                                 ? extractDomain(wikidataResult.officialWebsite)
                                 : extractDomain(submittedUrl),
        wikidataId:          wikidataResult?.wikidataId     || null,
        lei:                 wikidataResult?.lei             || null,
        cik:                 resolvedCik,
        isPublicCompany:     !!resolvedCik,
        resolvedIndustry:    wikidataResult?.resolvedIndustry || null,

        // Confidence signals (each shown separately — none treated as final)
        nameMatchScore,
        domainVerified:      domainCheck.match,
        domainMatchConfidence: domainCheck.confidence,
        edgarCrossCheckFound: !!edgarResult,
        overallConfidence,

        // Disclosures
        warnings,
        wikidataIsOneSignal: true,   // flag: downstream code must not treat Wikidata as sole authority
        resolvedAt:          new Date().toISOString(),
    };

    return entityProfile;
}


// ══════════════════════════════════════════════════════════════
// SECTION 7: INTEGRATION IN evaluate.js (backend)
// Add as Step 0, before scraper.scrape().
//
// FIND in src/routes/evaluate.js, the start of the evaluation
// pipeline (before scraper call). INSERT:
// ══════════════════════════════════════════════════════════════

/*
    // ── Step 0: Entity resolution (FIX-11) ───────────────────────────────
    const { resolveEntity } = require('../services/entity-resolver');

    const entityProfile = await resolveEntity(company, url);
    console.log('[HAI] Entity resolved:', entityProfile.resolvedName,
                '| confidence:', entityProfile.overallConfidence.toFixed(2),
                '| public:', entityProfile.isPublicCompany,
                '| warnings:', entityProfile.warnings.length);

    // Use resolved name for all evidence queries — but always log what the user submitted
    const queryName = entityProfile.resolvedName;
    const queryCik  = entityProfile.cik;

    // Pass entityProfile and queryName into supplementary evidence fetch:
    //   const suppResults = await fetchSupplementaryEvidence(queryName, url, industry, { entityProfile, queryCik });
    //
    // Add to response payload:
    //   entityProfile: entityProfile
    //
    // Store to hai_analysis_logs:
    //   entity_resolved_name:  entityProfile.resolvedName
    //   entity_wikidata_id:    entityProfile.wikidataId
    //   entity_is_public:      entityProfile.isPublicCompany
    //   entity_confidence:     entityProfile.overallConfidence
    //   entity_domain_match:   entityProfile.domainVerified
*/


// ══════════════════════════════════════════════════════════════
// SECTION 8: FRONTEND ENTITY CARD (bundle.js)
// Shown only when overallConfidence < 0.85 — clean matches are silent.
// The card is informational and transparent, not alarming.
// ══════════════════════════════════════════════════════════════

// In handleSuccess() in bundle.js, after receiving the payload:
//   window.currentEntityProfile = payload.entityProfile || null;
//
// In the results UI template, insert before the score display:
/*
    ${(function() {
        const ep = window.currentEntityProfile;
        if (!ep || ep.overallConfidence >= 0.85) return '';  // clean match — no card needed

        const _borderColor = ep.overallConfidence >= 0.6 ? '#f9a825' : '#e57373';
        const _bgColor     = ep.overallConfidence >= 0.6 ? '#fffde7' : '#fce4ec';
        const _topWarning  = ep.warnings.length > 0 ? ep.warnings[0] : 'Entity match is approximate.';

        return `<div style="margin:0 auto 16px; max-width:640px; padding:12px 16px;
                     background:${_bgColor}; border:1px solid ${_borderColor};
                     border-radius:8px; font-size:12px; line-height:1.5;">
            <div style="font-weight:600; color:#5d4037; margin-bottom:4px;">
              Entity verification note
            </div>
            <div style="color:#4a3000;">${_topWarning}</div>
            <div style="margin-top:6px; color:#777; font-size:11px;">
              Input: "${ep.inputName}" &nbsp;›&nbsp;
              ${ep.resolvedName !== ep.inputName
                  ? `Resolved to: <strong>${ep.resolvedName}</strong>`
                  : 'Name matched.'
              }
              &nbsp;|&nbsp; Match confidence: ${Math.round(ep.overallConfidence * 100)}%
              ${ep.isPublicCompany ? '&nbsp;|&nbsp; Public company' : ''}
            </div>
            ${ep.warnings.length > 1
                ? `<div style="margin-top:4px; font-size:11px; color:#9e7700;">
                     +${ep.warnings.length - 1} additional note(s) in the Evidence Appendix.
                   </div>`
                : ''
            }
        </div>`;
    })()}
*/


// ══════════════════════════════════════════════════════════════
// SECTION 9: Supabase columns
// ══════════════════════════════════════════════════════════════

const ENTITY_SQL = `
ALTER TABLE hai_analysis_logs
    ADD COLUMN IF NOT EXISTS entity_resolved_name  TEXT         DEFAULT '',
    ADD COLUMN IF NOT EXISTS entity_wikidata_id    TEXT         DEFAULT '',
    ADD COLUMN IF NOT EXISTS entity_is_public      BOOLEAN      DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS entity_confidence     NUMERIC(4,3) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS entity_domain_match   BOOLEAN      DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_hai_logs_entity_public
    ON hai_analysis_logs (entity_is_public, industry);
`;


module.exports = {
    resolveEntity,
    lookupWikidata,
    resolveEdgarCik,
    verifyDomainMatch,
    extractDomain,
    computeNameMatchScore,
    computeEntityConfidence,
    ENTITY_SQL
};
