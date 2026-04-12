'use strict';

// ---------------------------------------------------------------
// supplementary-evidence.js  —  HAI Supplementary Evidence Service
// Phase 4 (revised): Evidence-quality model
//
// ARCHITECTURE (unchanged):
//   Fetch pipeline → evaluate.js calls fetchSupplementarySignals
//   when scrape is partial/limited. Results travel as
//   supplementary_signals in the /evaluate response.
//
// WHAT CHANGED vs the original:
//   OLD: signal counts → directly boosted confidence and score
//   NEW: evidence items → mapped to specific rubric criteria →
//        weighted by source quality tier → validated for specificity →
//        used to gate maturity levels and derive criterion confidence
//
// CORE RULE:
//   Score  = evidence quality   (not signal volume)
//   Confidence = evidence credibility  (not source count)
// ---------------------------------------------------------------

const axios = require('axios');

const REQUEST_DELAY_MS = 800;
const TIMEOUT_MS       = 8000;

// ================================================================
// SOURCE QUALITY TIERS
// ================================================================
const SOURCE_TIER = {
    EDGAR:    'high',
    OECD:     'medium',
    ACADEMIC: 'medium',
    GITHUB:   'low',
    WAYBACK:  'low',
};

const TIER_WEIGHT = { high: 1.0, medium: 0.6, low: 0.25 };

// ================================================================
// CRITERION-TO-PILLAR MAP
// ================================================================
const PILLAR_CRITERIA = {
    trust:          ['trust_user_confidence','trust_consistency_of_behavior','trust_ethical_intent','trust_absence_of_manipulation'],
    accountability: ['accountability_ownership_of_outcomes','accountability_corrective_action','accountability_governance_and_oversight'],
    purpose:        ['purpose_mission_clarity','purpose_human_centered_intent','purpose_alignment_words_actions'],
    safety:         ['safety_risk_mitigation','safety_user_protection_mechanisms','safety_long_term_societal_safety'],
    transparency:   ['transparency_explainability','transparency_data_disclosure','transparency_communication_honesty'],
    impact:         ['impact_positive_human_outcomes','impact_shared_human_benefit','impact_measurability_of_impact','impact_durability_of_impact'],
};

// ================================================================
// SOURCE → PILLAR RELEVANCE MAP
//
// Evidence from a source can ONLY influence criteria in these pillars.
// Generic signals cannot affect unrelated criteria.
// ================================================================
const SOURCE_PILLAR_RELEVANCE = {
    EDGAR:    ['accountability', 'transparency', 'trust'],
    OECD:     ['trust', 'purpose', 'impact'],
    ACADEMIC: ['safety', 'impact'],
    GITHUB:   ['transparency', 'safety'],
    WAYBACK:  ['trust', 'transparency', 'accountability', 'purpose', 'safety', 'impact'],
};

// ================================================================
// CRITERION-SPECIFIC TERMS
// Used to determine whether evidence is criterion-specific or generic.
// ================================================================
const CRITERION_TERMS = {
    accountability_governance_and_oversight: ['governance', 'oversight', 'board', 'committee', 'charter', 'audit'],
    accountability_ownership_of_outcomes:    ['responsibility', 'accountab', 'ownership', 'incident'],
    accountability_corrective_action:        ['remediation', 'corrective', 'incident response', 'postmortem'],
    transparency_data_disclosure:            ['data disclosure', 'privacy', 'data governance', 'data policy'],
    transparency_explainability:             ['explainab', 'model card', 'system card', 'interpretab'],
    transparency_communication_honesty:      ['transparency report', 'disclosure', 'changelog'],
    trust_ethical_intent:                    ['ethics', 'ethical', 'principles', 'responsible ai', 'ai policy'],
    trust_user_confidence:                   ['user trust', 'trust center', 'feedback', 'support'],
    safety_risk_mitigation:                  ['risk', 'safety', 'red team', 'testing', 'assessment'],
    safety_long_term_societal_safety:        ['societal', 'long-term', 'impact', 'scenario'],
    purpose_mission_clarity:                 ['mission', 'purpose', 'strategy', 'vision'],
    purpose_human_centered_intent:           ['human', 'people', 'stakeholder', 'accessibility'],
    impact_measurability_of_impact:          ['metric', 'measur', 'outcome', 'impact report'],
    impact_positive_human_outcomes:          ['benefit', 'outcome', 'community', 'positive impact'],
};

// ================================================================
// MATURITY GATING TABLE
//
// Minimum evidence quality required to SUPPORT each maturity level.
// Low-trust sources alone cannot justify Level 3+.
// Levels 4-5 require high-trust criterion-specific evidence.
// ================================================================
const MATURITY_GATES = {
    5: { minTier: 'high',   requiresCriterionSpecific: true,  requiresCorroboration: true  },
    4: { minTier: 'high',   requiresCriterionSpecific: true,  requiresCorroboration: false },
    3: { minTier: 'medium', requiresCriterionSpecific: false, requiresCorroboration: false },
    2: { minTier: 'low',    requiresCriterionSpecific: false, requiresCorroboration: false },
    1: { minTier: null,     requiresCriterionSpecific: false, requiresCorroboration: false },
};

// ================================================================
// HELPERS
// ================================================================

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function safeGet(url, params = {}) {
    try {
        const resp = await axios.get(url, {
            params, timeout: TIMEOUT_MS,
            headers: { 'User-Agent': 'HAI-Index/2.0 (humanalignmentindex.com)' },
            validateStatus: () => true,
        });
        return resp.status === 200 ? resp.data : null;
    } catch (_) { return null; }
}

function isCriterionSpecific(text, criterionId) {
    const terms = CRITERION_TERMS[criterionId];
    if (!terms || !text) return false;
    const lower = text.toLowerCase();
    return terms.some(t => lower.includes(t));
}

// Every piece of evidence carries full traceability fields.
function makeEvidenceItem({ source, sourceTier, text, url, relevantPillars, criterionSpecificFor, evidenceType }) {
    return {
        source,
        sourceTier,
        tierWeight:           TIER_WEIGHT[sourceTier],
        text:                 text || '',
        url:                  url  || '',
        relevantPillars:      relevantPillars || [],
        criterionSpecificFor: criterionSpecificFor || [],
        evidenceType,
        role: null,  // 'justifies' | 'supports' — assigned in mapEvidenceToCriteria
    };
}

// ================================================================
// SOURCE FETCHERS (fetch pipeline unchanged; return shape updated)
// ================================================================

async function fetchEdgar(companyName) {
    const items = [];
    const TERMS = ['responsible AI', 'AI governance', 'AI ethics', 'artificial intelligence policy', 'AI risk'];
    for (const term of TERMS.slice(0, 3)) {
        const data = await safeGet('https://efts.sec.gov/LATEST/search-index', {
            q: `"${companyName}" "${term}"`, dateRange: 'custom',
            startdt: '2022-01-01', forms: '10-K,DEF 14A',
        });
        await sleep(REQUEST_DELAY_MS);
        const hits = data && data.hits && data.hits.total ? data.hits.total.value : 0;
        if (hits > 0) {
            const criterionSpecific = Object.keys(CRITERION_TERMS).filter(c => isCriterionSpecific(term, c));
            items.push(makeEvidenceItem({
                source: 'EDGAR', sourceTier: SOURCE_TIER.EDGAR,
                text: 'SEC filing mentions "' + term + '" (' + hits + ' hit' + (hits > 1 ? 's' : '') + ')',
                url:  'https://efts.sec.gov/LATEST/search-index?q=' + encodeURIComponent('"'+companyName+'" "'+term+'"') + '&forms=10-K',
                relevantPillars: SOURCE_PILLAR_RELEVANCE.EDGAR,
                criterionSpecificFor: criterionSpecific,
                evidenceType: 'governance',
            }));
        }
    }
    return items;
}

async function fetchWayback(companyUrl) {
    const items = [];
    let origin;
    try { origin = new URL(companyUrl).origin; } catch (_) { return []; }
    // Only governance-specific paths — /privacy and /terms are generic, excluded
    const PATHS = ['/ai-policy', '/responsible-ai', '/ethics', '/governance', '/ai-principles', '/trust'];
    for (const path of PATHS) {
        const data = await safeGet('https://archive.org/wayback/available', { url: origin + path });
        await sleep(400);
        const snap = data && data.archived_snapshots && data.archived_snapshots.closest;
        if (snap && snap.available && snap.status === '200') {
            const criterionSpecific = Object.keys(CRITERION_TERMS).filter(c => isCriterionSpecific(path, c));
            items.push(makeEvidenceItem({
                source: 'WAYBACK', sourceTier: SOURCE_TIER.WAYBACK,
                text: 'Archived governance page: ' + path + ' (cached ' + snap.timestamp + ')',
                url:  snap.url,
                relevantPillars: SOURCE_PILLAR_RELEVANCE.WAYBACK,
                criterionSpecificFor: criterionSpecific,
                evidenceType: 'governance',  // page existence only — low-trust
            }));
        }
    }
    return items;
}

async function fetchOecd(companyName) {
    const items = [];
    const data = await safeGet('https://oecd.ai/en/wonk/api/search', { q: companyName, type: 'private_sector', lang: 'en' });
    await sleep(REQUEST_DELAY_MS);
    if (data && data.results) {
        for (const r of data.results.slice(0, 3)) {
            if (!JSON.stringify(r).toLowerCase().includes(companyName.toLowerCase())) continue;
            const title = r.title || '';
            const criterionSpecific = Object.keys(CRITERION_TERMS).filter(c => isCriterionSpecific(title, c));
            items.push(makeEvidenceItem({
                source: 'OECD', sourceTier: SOURCE_TIER.OECD,
                text: title || 'OECD AI Policy Observatory listing',
                url:  r.url || '',
                relevantPillars: SOURCE_PILLAR_RELEVANCE.OECD,
                criterionSpecificFor: criterionSpecific,
                evidenceType: 'external',
            }));
        }
    }
    return items;
}

async function fetchGithub(companyName, githubToken) {
    const items = [];
    const headers = githubToken
        ? { 'Authorization': 'token ' + githubToken, 'User-Agent': 'HAI-Index/2.0' }
        : { 'User-Agent': 'HAI-Index/2.0' };
    const orgSlug = companyName.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/-+/g, '-');
    const KEYWORDS = ['responsible-ai', 'ai-ethics', 'model-card', 'ai-safety', 'ai-principles'];
    for (const kw of KEYWORDS.slice(0, 3)) {
        try {
            const resp = await axios.get('https://api.github.com/search/repositories', {
                params: { q: 'org:' + orgSlug + ' ' + kw, per_page: 3 },
                timeout: TIMEOUT_MS, headers, validateStatus: () => true,
            });
            await sleep(REQUEST_DELAY_MS);
            if (resp.status !== 200 || !resp.data || !resp.data.total_count) continue;
            for (const repo of (resp.data.items || []).slice(0, 2)) {
                const repoText = repo.full_name + ' ' + (repo.description || '');
                const criterionSpecific = Object.keys(CRITERION_TERMS).filter(c => isCriterionSpecific(repoText, c));
                items.push(makeEvidenceItem({
                    source: 'GITHUB', sourceTier: SOURCE_TIER.GITHUB,
                    text: 'Public repo: ' + repo.full_name + (repo.description ? ' — ' + repo.description : ''),
                    url:  repo.html_url,
                    relevantPillars: SOURCE_PILLAR_RELEVANCE.GITHUB,
                    criterionSpecificFor: criterionSpecific,
                    evidenceType: 'operational',
                }));
            }
        } catch (_) {}
    }
    return items;
}

async function fetchAcademic(companyName) {
    const items = [];
    for (const term of ['responsible AI', 'AI safety', 'AI ethics']) {
        const data = await safeGet('https://api.semanticscholar.org/graph/v1/paper/search', {
            query: companyName + ' ' + term, fields: 'title,year,authors', limit: 5,
        });
        await sleep(REQUEST_DELAY_MS);
        if (!data || !data.data || !data.data.length) continue;
        for (const paper of data.data.slice(0, 2)) {
            if (!paper.title) continue;
            const criterionSpecific = Object.keys(CRITERION_TERMS).filter(c => isCriterionSpecific(paper.title, c));
            items.push(makeEvidenceItem({
                source: 'ACADEMIC', sourceTier: SOURCE_TIER.ACADEMIC,
                text: paper.title + (paper.year ? ' (' + paper.year + ')' : ''),
                url:  '',
                relevantPillars: SOURCE_PILLAR_RELEVANCE.ACADEMIC,
                criterionSpecificFor: criterionSpecific,
                evidenceType: 'external',
            }));
        }
        if (items.length >= 3) break;
    }
    return items;
}

async function fetchWikipediaMeta(companyName) {
    const data = await safeGet('https://en.wikipedia.org/w/api.php', {
        action: 'query', titles: companyName, prop: 'categories', format: 'json', redirects: 1,
    });
    if (!data) return { isPublic: false };
    const pages = (data.query && data.query.pages) || {};
    for (const [id, page] of Object.entries(pages)) {
        if (id === '-1') continue;
        const cats = (page.categories || []).map(c => c.title.toLowerCase());
        return {
            isPublic: cats.some(c => c.includes('publicly traded') || c.includes('nasdaq') || c.includes('nyse')),
            categories: cats.slice(0, 8),
        };
    }
    return { isPublic: false };
}

// ================================================================
// EVIDENCE → CRITERIA MAPPING
//
// Produces: criterionId → [evidenceItem, ...]
//
// An item reaches a criterion only if:
//   1. Its relevantPillars includes the criterion's pillar, AND
//   2. It is criterion-specific OR high-trust
//
// Low-trust non-specific evidence is excluded entirely.
// ================================================================
function mapEvidenceToCriteria(evidenceItems) {
    const pillarToCriteria = {};
    for (const [pillar, criteria] of Object.entries(PILLAR_CRITERIA)) {
        pillarToCriteria[pillar] = criteria;
    }

    const criterionEvidence = {};
    for (const criteria of Object.values(PILLAR_CRITERIA)) {
        for (const critId of criteria) {
            criterionEvidence[critId] = [];
        }
    }

    for (const item of evidenceItems) {
        for (const pillar of (item.relevantPillars || [])) {
            const criteria = pillarToCriteria[pillar] || [];
            for (const critId of criteria) {
                const isSpecific = item.criterionSpecificFor.includes(critId);

                // ADMISSIBILITY RULES (no pillar spillover):
                //
                // HIGH trust: admitted ONLY if criterion-specific.
                //   Rationale: a 10-K mention of "AI governance" is specific to
                //   accountability_governance_and_oversight, not to every criterion in
                //   the accountability pillar. Source quality doesn't override specificity.
                //
                // MEDIUM trust: admitted if criterion-specific (justifies) OR as
                //   broad corroboration within the pillar (supports). Medium sources
                //   are credible enough to contribute supporting context even without
                //   an exact criterion match, but cannot independently justify a level.
                //
                // LOW trust: admitted ONLY if criterion-specific.
                //   Low-trust non-specific evidence is excluded entirely.
                //   Rationale: a cached /ai-policy URL or GitHub keyword repo is too
                //   weak and indirect to influence criteria it doesn't directly address.

                if (item.sourceTier === 'high') {
                    if (!isSpecific) continue;          // high-trust requires criterion match
                    criterionEvidence[critId].push(Object.assign({}, item, { role: 'justifies' }));

                } else if (item.sourceTier === 'medium') {
                    // Medium: specific = justifies, non-specific = supports (corroboration)
                    criterionEvidence[critId].push(Object.assign({}, item, {
                        role: isSpecific ? 'justifies' : 'supports',
                    }));

                } else {
                    // LOW trust: criterion-specific only
                    if (!isSpecific) continue;
                    criterionEvidence[critId].push(Object.assign({}, item, { role: 'supports' }));
                    // Note: low-trust is always 'supports' even when specific —
                    // it can corroborate but never independently justify a level.
                }
            }
        }
    }

    return criterionEvidence;
}

// ================================================================
// MATURITY GATE CHECK
//
// Returns the maximum maturity level that supplementary evidence
// can SUPPORT for a criterion. Used to cap over-inflation from
// OpenAI when scrape was partial.
// ================================================================
function checkMaturityGate(criterionId, evidenceForCriterion) {
    if (!evidenceForCriterion || evidenceForCriterion.length === 0) {
        return { maxSupportableLevel: 1, gateReason: 'no_supplementary_evidence', evidenceUsed: [] };
    }

    const highTrust    = evidenceForCriterion.filter(e => e.sourceTier === 'high');
    const mediumTrust  = evidenceForCriterion.filter(e => e.sourceTier === 'medium');
    const justifying   = evidenceForCriterion.filter(e => e.role === 'justifies');
    const corroborated = evidenceForCriterion.length >= 2;

    // Level 5: HIGH trust + criterion-specific + corroborated by second independent source
    if (highTrust.length > 0 && justifying.length > 0 && corroborated) {
        return { maxSupportableLevel: 5, gateReason: 'high_trust_specific_corroborated', evidenceUsed: evidenceForCriterion };
    }
    // Level 4: HIGH trust + criterion-specific (corroboration not required)
    if (highTrust.length > 0 && justifying.length > 0) {
        return { maxSupportableLevel: 4, gateReason: 'high_trust_specific', evidenceUsed: highTrust };
    }
    // Level 3: requires MEDIUM trust, OR strong criterion-specific evidence that is
    //   corroborated by a second source. Weak corroboration alone (2+ low-trust
    //   non-specific items) is NOT sufficient — removed per methodology revision.
    const hasSpecificEvidence = evidenceForCriterion.some(e => e.role === 'justifies');
    const corroboratedSpecific = corroborated && hasSpecificEvidence;
    if (mediumTrust.length > 0 || corroboratedSpecific) {
        return { maxSupportableLevel: 3, gateReason: mediumTrust.length > 0 ? 'medium_trust' : 'specific_corroborated', evidenceUsed: evidenceForCriterion };
    }
    // Level 2: any single admissible evidence item (low-trust specific, medium-trust generic)
    return { maxSupportableLevel: 2, gateReason: 'weak_evidence_corroboration_only', evidenceUsed: evidenceForCriterion };
}

// ================================================================
// CRITERION CONFIDENCE
//
// OLD: confidence += signalCount * constant
// NEW: confidence = f(source tier, specificity, corroboration)
// ================================================================
function computeCriterionConfidence(evidenceForCriterion) {
    if (!evidenceForCriterion || evidenceForCriterion.length === 0) return 0;

    let score = 0;
    for (const item of evidenceForCriterion) {
        const tierWeight     = TIER_WEIGHT[item.sourceTier] || 0;
        const specificityMul = item.role === 'justifies' ? 1.0 : 0.5;
        score += tierWeight * specificityMul * 30;  // max 30 per high-trust specific item
    }

    // Corroboration bonus: multiple independent sources
    const uniqueSources = new Set(evidenceForCriterion.map(e => e.source)).size;
    if (uniqueSources >= 2) score += 10;
    if (uniqueSources >= 3) score += 5;

    return Math.min(Math.round(score), 100);
}

// ================================================================
// EVALUATE SUPPLEMENTARY IMPACT
//
// Produces the structured assessment returned to the frontend.
// Contains per-criterion evidence maps and quality assessments —
// NOT raw signal counts.
// ================================================================
function evaluateSupplementaryImpact(evidenceItems) {
    const criterionEvidence   = mapEvidenceToCriteria(evidenceItems);
    const maturityGates       = {};
    const criterionConfidence = {};

    for (const critId of Object.keys(criterionEvidence)) {
        const items         = criterionEvidence[critId];
        maturityGates[critId]       = checkMaturityGate(critId, items);
        criterionConfidence[critId] = computeCriterionConfidence(items);
    }

    const hasHigh              = evidenceItems.some(e => e.sourceTier === 'high');
    const hasMedium            = evidenceItems.some(e => e.sourceTier === 'medium');
    const hasCriterionSpecific = evidenceItems.some(e => e.criterionSpecificFor.length > 0);

    let overallTier = 'none';
    if (hasHigh && hasCriterionSpecific)  overallTier = 'high';
    else if (hasHigh || hasMedium)        overallTier = 'medium';
    else if (evidenceItems.length > 0)    overallTier = 'low';

    return {
        criterionEvidence,
        maturityGates,
        criterionConfidence,
        overallTier,
        hasHighTrustEvidence: hasHigh,
        cappedCriteria:  [],   // populated by applySupplementaryToScoring
        traceability:    evidenceItems,
        sourceCounts: {
            edgar:    evidenceItems.filter(e => e.source === 'EDGAR').length,
            oecd:     evidenceItems.filter(e => e.source === 'OECD').length,
            github:   evidenceItems.filter(e => e.source === 'GITHUB').length,
            wayback:  evidenceItems.filter(e => e.source === 'WAYBACK').length,
            academic: evidenceItems.filter(e => e.source === 'ACADEMIC').length,
        },
        totalItems: evidenceItems.length,
    };
}

// ================================================================
// MAIN EXPORT
// ================================================================
async function fetchSupplementarySignals(companyName, companyUrl, options) {
    options = options || {};
    console.log('[supplementary] Fetching for: ' + companyName);

    const [edgarItems, oecdItems, academicItems, wikiMeta] = await Promise.all([
        fetchEdgar(companyName).catch(() => []),
        fetchOecd(companyName).catch(() => []),
        fetchAcademic(companyName).catch(() => []),
        fetchWikipediaMeta(companyName).catch(() => ({ isPublic: false })),
    ]);

    const waybackItems = options.skipWayback ? [] :
        await fetchWayback(companyUrl).catch(() => []);
    const githubItems  = await fetchGithub(companyName, options.githubToken).catch(() => []);

    const allItems = [].concat(edgarItems, oecdItems, academicItems, waybackItems, githubItems);
    const impact   = evaluateSupplementaryImpact(allItems);

    console.log(
        '[supplementary] ' + companyName +
        ' — items: ' + allItems.length +
        ' tier: ' + impact.overallTier +
        ' edgar: ' + impact.sourceCounts.edgar +
        ' oecd: '  + impact.sourceCounts.oecd +
        ' github: ' + impact.sourceCounts.github +
        ' wayback: ' + impact.sourceCounts.wayback +
        ' academic: ' + impact.sourceCounts.academic
    );

    return {
        // Structured evidence assessment — used by scoring
        impact,

        // Source counts — for logging ONLY, NOT for direct scoring
        edgarSignals:    impact.sourceCounts.edgar,
        waybackSignals:  impact.sourceCounts.wayback,
        oecdSignals:     impact.sourceCounts.oecd,
        githubSignals:   impact.sourceCounts.github,
        academicSignals: impact.sourceCounts.academic,
        totalSignals:    allItems.length,   // kept for log compatibility

        isPublicCompany: wikiMeta.isPublic || false,
        evidence:        allItems,
        sourceBreakdown: impact.sourceCounts,
    };
}

// ================================================================
// SCORING INTEGRATION HELPER
//
// Called by bundle.js updateDashboard when supplementary data is
// available. Takes the impact assessment and current rubric state.
//
// KEY RULES:
//   - Can CORROBORATE existing levels → modest confidence boost
//   - Can CAP levels during partial_evaluation (OpenAI had limited data)
//   - NEVER inflates score
//   - NEVER boosts confidence from zero to high on its own
// ================================================================
function applySupplementaryToScoring(supplementaryResult, rubricState) {
    const empty = { adjustedState: rubricState, confidenceAdjustments: {}, cappedCriteria: [], scoringLog: [] };
    if (!supplementaryResult || !supplementaryResult.impact) return empty;

    const impact         = supplementaryResult.impact;
    const adjustedState  = Object.assign({}, rubricState);
    const confidenceAdj  = {};
    const cappedCriteria = [];
    const scoringLog     = [];

    for (const critId of Object.keys(rubricState)) {
        const currentLevel = (rubricState[critId] && rubricState[critId].level) || 1;
        const gate         = impact.maturityGates[critId];
        const critConf     = impact.criterionConfidence[critId] || 0;

        if (!gate) continue;

        // Log when OpenAI level exceeds what supplementary evidence supports.
        // Actual capping is applied in bundle.js only during partial_evaluation.
        if (currentLevel > gate.maxSupportableLevel) {
            scoringLog.push(
                critId + ': OpenAI level ' + currentLevel +
                ' exceeds gate ' + gate.maxSupportableLevel +
                ' (' + gate.gateReason + ')'
            );
        }

        // Confidence boost: supplementary evidence corroborates existing level.
        // Max 15 pts for high-trust specific, less for lower tiers.
        // Never bootstraps from 0 to high confidence.
        if (critConf > 0) {
            const maxBoost = impact.hasHighTrustEvidence ? 15 : 8;
            const boost    = Math.min(critConf * 0.15, maxBoost);
            if (boost > 0) {
                confidenceAdj[critId] = Math.round(boost);
                scoringLog.push(critId + ': confidence +' + Math.round(boost) + ' (' + gate.gateReason + ')');
            }
        }
    }

    impact.cappedCriteria = cappedCriteria;
    return { adjustedState, confidenceAdjustments: confidenceAdj, cappedCriteria, scoringLog };
}

module.exports = {
    fetchSupplementarySignals,
    applySupplementaryToScoring,
    // Exported for testing
    mapEvidenceToCriteria,
    checkMaturityGate,
    computeCriterionConfidence,
    evaluateSupplementaryImpact,
    SOURCE_TIER,
    TIER_WEIGHT,
    MATURITY_GATES,
};
