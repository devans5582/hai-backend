'use strict';

// src/services/supplementary-evidence.js
// Phase 4 evidence-quality fetch service — Phase 6 enhanced
//
// Triggered by evaluate.js when website scrape returns partial or limited access.
// Queries five public sources, maps evidence to rubric criteria, applies
// materiality weighting, time decay, execution detection, and negative overrides.
//
// Core principle: evidence must map to specific rubric criteria.
// Source quality determines what that evidence can support.
// Signal volume does not affect score.

const axios = require('axios');

// ── Phase 6 service imports ─────────────────────────────────────────────────
const { annotateWithExecutionScore, executionBonus } = require('./proof-of-execution');
const { annotateWithTimeDecay }                       = require('./time-decay');
const {
    computeWeightedContribution,
    CRITERION_MATERIALITY,
    getMaterialityWeight,
}                                                     = require('./evidence-weighting');
const { applyNegativeOverrides, classifyNegativeSignal } = require('./negative-signal-overrides');

// ── Rubric definition (criteria per pillar) ────────────────────────────────
const RUBRIC_DEF = {
    pillars: [
        {
            id: 'trust',
            criteria: [
                { id: 'trust_user_confidence',          label: 'User Confidence' },
                { id: 'trust_consistency_of_behavior',  label: 'Consistency of Behavior' },
                { id: 'trust_ethical_intent',           label: 'Ethical Intent' },
                { id: 'trust_absence_of_manipulation',  label: 'Absence of Manipulation' },
            ]
        },
        {
            id: 'accountability',
            criteria: [
                { id: 'accountability_ownership_of_outcomes',    label: 'Ownership of Outcomes' },
                { id: 'accountability_corrective_action',        label: 'Corrective Action' },
                { id: 'accountability_governance_and_oversight', label: 'Governance and Oversight' },
            ]
        },
        {
            id: 'purpose',
            criteria: [
                { id: 'purpose_mission_clarity',         label: 'Mission Clarity' },
                { id: 'purpose_human_centered_intent',   label: 'Human-Centered Intent' },
                { id: 'purpose_alignment_words_actions', label: 'Alignment: Words & Actions' },
            ]
        },
        {
            id: 'safety',
            criteria: [
                { id: 'safety_risk_mitigation',              label: 'Risk Mitigation' },
                { id: 'safety_user_protection_mechanisms',   label: 'User Protection Mechanisms' },
                { id: 'safety_long_term_societal_safety',    label: 'Long-Term Societal Safety' },
            ]
        },
        {
            id: 'transparency',
            criteria: [
                { id: 'transparency_explainability',         label: 'Explainability' },
                { id: 'transparency_data_disclosure',        label: 'Data Disclosure' },
                { id: 'transparency_communication_honesty',  label: 'Communication Honesty' },
            ]
        },
        {
            id: 'impact',
            criteria: [
                { id: 'impact_positive_human_outcomes',  label: 'Positive Human Outcomes' },
                { id: 'impact_shared_human_benefit',     label: 'Shared Human Benefit' },
                { id: 'impact_measurability_of_impact',  label: 'Measurability of Impact' },
                { id: 'impact_durability_of_impact',     label: 'Durability of Impact' },
            ]
        },
    ]
};

// ── Source → Pillar relevance mapping ──────────────────────────────────────
const SOURCE_PILLAR_MAP = {
    EDGAR:    ['accountability', 'transparency', 'trust'],
    ISO_42001: ['safety', 'accountability', 'trust'],
    NIST_RMF: ['safety', 'accountability', 'purpose'],
    GOVINFO:  ['accountability', 'transparency', 'purpose'],
    OECD:     ['trust', 'purpose', 'impact'],
    ACADEMIC: ['safety', 'impact'],
    NEWS:     ['trust', 'safety'],
    NEWS_NEGATIVE: ['trust', 'safety', 'accountability'],
    GITHUB:   ['transparency', 'safety'],
    WAYBACK:  ['trust', 'accountability', 'purpose', 'safety', 'transparency', 'impact'],
};

// Source tier weights
const SOURCE_TIER = {
    EDGAR:    { tier: 'high',   weight: 1.0 },
    ISO_42001: { tier: 'high',  weight: 1.0 },
    NIST_RMF: { tier: 'high',   weight: 1.0 },
    GOVINFO:  { tier: 'high',   weight: 1.0 },
    OECD:     { tier: 'medium', weight: 0.6 },
    ACADEMIC: { tier: 'medium', weight: 0.6 },
    NEWS:     { tier: 'medium', weight: 0.6 },
    NEWS_NEGATIVE: { tier: 'medium', weight: 0.6 },
    GITHUB:   { tier: 'low',    weight: 0.25 },
    WAYBACK:  { tier: 'low',    weight: 0.25 },
};

// Keyword patterns mapping evidence text to specific criterion IDs
const CRITERION_KEYWORD_MAP = {
    trust_user_confidence:                  ['user trust', 'user confidence', 'trust center', 'ai trust statement', 'feedback channel', 'user expectations', 'ai transparency', 'incident log'],
    trust_consistency_of_behavior:          ['model consistency', 'testing plan', 'qa process', 'change log', 'release log', 'drift monitoring', 'model versioning'],
    trust_ethical_intent:                   ['ethical ai', 'ai ethics', 'ethics policy', 'ethical principles', 'responsible ai', 'ai principles'],
    trust_absence_of_manipulation:          ['dark patterns', 'manipulation', 'deceptive design', 'user autonomy', 'consent', 'no manipulation'],
    accountability_ownership_of_outcomes:   ['ai owner', 'responsible person', 'accountable', 'named owner', 'ai governance owner', 'chief ai', 'ai officer'],
    accountability_corrective_action:       ['corrective action', 'incident response', 'remediation', 'error correction', 'ai incident', 'model failure'],
    accountability_governance_and_oversight:['governance committee', 'oversight', 'ai board', 'governance framework', 'ai governance', 'board oversight'],
    purpose_mission_clarity:                ['mission', 'purpose statement', 'ai purpose', 'why we use ai', 'strategic ai', 'ai mission'],
    purpose_human_centered_intent:          ['human-centered', 'human-centric', 'people first', 'human benefit', 'serving humans', 'human need'],
    purpose_alignment_words_actions:        ['policy alignment', 'practice alignment', 'words and actions', 'commitment', 'following through'],
    safety_risk_mitigation:                 ['risk assessment', 'risk mitigation', 'ai risk', 'risk management', 'risk framework', 'hazard', 'failure mode'],
    safety_user_protection_mechanisms:      ['safeguard', 'user protection', 'safety mechanism', 'harm prevention', 'safety protocol', 'content filter'],
    safety_long_term_societal_safety:       ['societal safety', 'long-term safety', 'systemic risk', 'societal impact', 'existential', 'broader safety'],
    transparency_explainability:            ['explainability', 'explainable ai', 'how ai works', 'decision explanation', 'xai', 'interpretability'],
    transparency_data_disclosure:           ['data disclosure', 'data practices', 'data handling', 'privacy policy', 'data use', 'data transparency', 'gdpr'],
    transparency_communication_honesty:     ['honest communication', 'ai disclosure', 'telling users', 'labelling ai', 'ai identification'],
    impact_positive_human_outcomes:         ['human outcomes', 'positive impact', 'user benefit', 'lives improved', 'impact report', 'social good'],
    impact_shared_human_benefit:            ['shared benefit', 'societal benefit', 'community benefit', 'public good', 'equitable'],
    impact_measurability_of_impact:         ['impact metrics', 'measuring impact', 'impact measurement', 'kpi', 'outcomes tracked', 'results published'],
    impact_durability_of_impact:            ['sustained impact', 'long-term impact', 'durable benefit', 'lasting change'],
};

// ── Source fetch functions ──────────────────────────────────────────────────

async function fetchEdgar(companyName) {
    const results = [];
    try {
        const query = encodeURIComponent(`"${companyName}" artificial intelligence governance responsible`);
        const url   = `https://efts.sec.gov/LATEST/search-index?q=${query}&dateRange=custom&startdt=2020-01-01&forms=10-K,DEF+14A`;
        const res   = await axios.get(url, {
            timeout: 8000,
            headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
        });
        const hits  = res.data?.hits?.hits || [];

        hits.slice(0, 3).forEach(hit => {
            const src = hit._source || {};
            const text = [src.period_of_report, src.display_names?.[0], src.form_type].filter(Boolean).join(' — ');
            results.push({
                source:           'EDGAR',
                sourceTier:       'high',
                tierWeight:       1.0,
                text:             `SEC ${src.form_type || '10-K'} filing: ${src.display_names?.[0] || companyName}. ${src.period_of_report ? 'Period: ' + src.period_of_report : ''}`,
                url:              src.file_date ? `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=${encodeURIComponent(companyName)}&type=10-K&dateb=&owner=include&count=5` : null,
                dateIssued:       src.file_date  || null,
                relevantPillars:  SOURCE_PILLAR_MAP.EDGAR,
                criterionSpecificFor: mapTextToCriteria(text, SOURCE_PILLAR_MAP.EDGAR),
                evidenceType:     'external',
                role:             'justifies',
            });
        });
    } catch (err) {
        console.log('[HAI] EDGAR fetch failed:', err.message);
    }
    return results;
}

async function fetchOecd(companyName) {
    const results = [];
    try {
        const query = encodeURIComponent(companyName);
        const url   = `https://oecd.ai/en/wonk/api/search?q=${query}&type=private_sector&limit=3`;
        const res   = await axios.get(url, {
            timeout: 7000,
            headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
        });
        const items = res.data?.results || res.data?.items || [];

        items.slice(0, 2).forEach(item => {
            const text = item.title || item.name || item.description || '';
            results.push({
                source:           'OECD',
                sourceTier:       'medium',
                tierWeight:       0.6,
                text:             `OECD AI Observatory: ${text.slice(0, 200)}`,
                url:              item.url || 'https://oecd.ai/en/wonk',
                dateIssued:       item.date || item.published_date || null,
                relevantPillars:  SOURCE_PILLAR_MAP.OECD,
                criterionSpecificFor: mapTextToCriteria(text, SOURCE_PILLAR_MAP.OECD),
                evidenceType:     'governance',
                role:             'supports',
            });
        });
    } catch (err) {
        console.log('[HAI] OECD fetch failed:', err.message);
    }
    return results;
}

async function fetchAcademic(companyName) {
    const results = [];
    try {
        const query = encodeURIComponent(`${companyName} responsible AI governance`);
        const url   = `https://api.semanticscholar.org/graph/v1/paper/search?query=${query}&limit=3&fields=title,year,authors,externalIds`;
        const res   = await axios.get(url, {
            timeout: 7000,
            headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
        });
        const papers = res.data?.data || [];

        papers.slice(0, 2).forEach(paper => {
            const title   = paper.title || '';
            const authors = (paper.authors || []).map(a => a.name).join(', ').slice(0, 100);
            const doi     = paper.externalIds?.DOI;
            results.push({
                source:           'ACADEMIC',
                sourceTier:       'medium',
                tierWeight:       0.6,
                text:             `Academic paper: "${title}" (${paper.year || 'undated'}). Authors: ${authors || 'unknown'}.`,
                url:              doi ? `https://doi.org/${doi}` : 'https://www.semanticscholar.org/',
                dateIssued:       paper.year ? String(paper.year) : null,
                relevantPillars:  SOURCE_PILLAR_MAP.ACADEMIC,
                criterionSpecificFor: mapTextToCriteria(title, SOURCE_PILLAR_MAP.ACADEMIC),
                evidenceType:     'external',
                role:             'supports',
            });
        });
    } catch (err) {
        console.log('[HAI] Academic fetch failed:', err.message);
    }
    return results;
}

async function fetchWayback(companyUrl) {
    const results = [];
    const GOVERNANCE_PATHS = [
        '/responsible-ai', '/ai-governance', '/ai-ethics', '/ai-principles',
        '/trust', '/trust-center', '/ethics', '/privacy', '/governance',
        '/transparency', '/responsible-technology', '/how-we-use-ai',
        '/sustainability', '/impact', '/about/ai',
    ];

    // Test a sample of paths — not all, to stay within rate limits
    const pathsToCheck = GOVERNANCE_PATHS.slice(0, 5);
    const baseUrl = companyUrl.replace(/\/$/, '');

    for (const path of pathsToCheck) {
        try {
            const archiveUrl = `https://archive.org/wayback/available?url=${encodeURIComponent(baseUrl + path)}`;
            const res = await axios.get(archiveUrl, {
                timeout: 5000,
                headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
            });
            const snap = res.data?.archived_snapshots?.closest;
            if (snap && snap.available && snap.status === '200') {
                results.push({
                    source:           'WAYBACK',
                    sourceTier:       'low',
                    tierWeight:       0.25,
                    text:             `Archived governance page found: ${baseUrl}${path} (snapshot: ${snap.timestamp?.slice(0,8) || 'unknown date'})`,
                    url:              snap.url || null,
                    dateIssued:       snap.timestamp ? snap.timestamp.slice(0,4) + '-' + snap.timestamp.slice(4,6) + '-' + snap.timestamp.slice(6,8) : null,
                    relevantPillars:  SOURCE_PILLAR_MAP.WAYBACK,
                    criterionSpecificFor: mapTextToCriteria(path, SOURCE_PILLAR_MAP.WAYBACK),
                    evidenceType:     'governance',
                    role:             'supports',  // Wayback can never justify — corroboration only
                });
            }
        } catch (err) {
            // Individual path failures are non-blocking
        }
        // Respect Wayback rate limits
        await new Promise(r => setTimeout(r, 300));
    }
    return results;
}

async function fetchGithub(companyName) {
    const results = [];
    try {
        const headers = { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' };
        if (process.env.GITHUB_TOKEN) {
            headers['Authorization'] = `token ${process.env.GITHUB_TOKEN}`;
        }
        const slug  = companyName.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/-+/g, '-');
        const query = encodeURIComponent(`org:${slug} responsible-ai OR ai-ethics OR ai-governance`);
        const url   = `https://api.github.com/search/repositories?q=${query}&per_page=3`;
        const res   = await axios.get(url, { timeout: 6000, headers });
        const repos = res.data?.items || [];

        repos.slice(0, 2).forEach(repo => {
            results.push({
                source:           'GITHUB',
                sourceTier:       'low',
                tierWeight:       0.25,
                text:             `GitHub repository: ${repo.full_name} — "${repo.description || 'no description'}". Stars: ${repo.stargazers_count || 0}.`,
                url:              repo.html_url || null,
                dateIssued:       repo.updated_at ? repo.updated_at.slice(0, 10) : null,
                relevantPillars:  SOURCE_PILLAR_MAP.GITHUB,
                criterionSpecificFor: mapTextToCriteria((repo.name + ' ' + (repo.description || '')), SOURCE_PILLAR_MAP.GITHUB),
                evidenceType:     'operational',
                role:             'supports',
            });
        });
    } catch (err) {
        console.log('[HAI] GitHub fetch failed:', err.message);
    }
    return results;
}

async function fetchWikipediaMeta(companyName) {
    // Metadata only — not scored. Used to determine isPublicCompany.
    try {
        const query = encodeURIComponent(companyName);
        const url   = `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${query}&srlimit=1&format=json&origin=*`;
        const res   = await axios.get(url, {
            timeout: 5000,
            headers: { 'User-Agent': 'HAI-Assessment-Bot/1.0 (humanalignmentindex.com)' }
        });
        const result = res.data?.query?.search?.[0];
        if (!result) return { isPublicCompany: false };

        // Heuristic: if the snippet mentions stock symbols, NYSE, NASDAQ, LSE it's likely public
        const snippet = (result.snippet || '').toLowerCase();
        const isPublic = /nasdaq|nyse|lse|stock exchange|publicly traded|ticker symbol|shares listed/.test(snippet);
        return { isPublicCompany: isPublic, wikipediaTitle: result.title };
    } catch (err) {
        return { isPublicCompany: false };
    }
}

async function fetchNewsSignals(companyName) {
    // Google News RSS — medium trust, detects both positive governance news
    // and negative signals (regulatory actions, incidents).
    const results = [];
    try {
        const query    = encodeURIComponent(`"${companyName}" AI governance`);
        const rssUrl   = `https://news.google.com/rss/search?q=${query}&hl=en-US&gl=US&ceid=US:en`;
        const res      = await axios.get(rssUrl, {
            timeout: 6000,
            headers: { 'Accept': 'application/rss+xml, text/xml', 'User-Agent': 'HAI-Assessment-Bot/1.0' }
        });
        const xml    = (res.data || '').toString();
        const titles = [...xml.matchAll(/<title><!\[CDATA\[([^\]]+)\]\]><\/title>/g)]
            .map(m => m[1])
            .filter(t => !t.includes('Google News'))
            .slice(0, 4);

        const NEGATIVE_PATTERNS = [
            'enforcement action', 'ftc', 'gdpr fine', 'ico penalty', 'court order',
            'regulatory order', 'class action', 'lawsuit filed', 'under investigation',
            'regulatory inquiry', 'ai incident', 'ai harm', 'data breach confirmed',
            'ai failure', 'ai bias documented', 'policy not followed', 'contradicts stated policy'
        ];

        titles.forEach(title => {
            const _lower   = title.toLowerCase();
            const isNegative = NEGATIVE_PATTERNS.some(p => _lower.includes(p));
            const signal   = classifyNegativeSignal(isNegative ? {
                source: 'NEWS_NEGATIVE', role: 'contradicts', isNegativeSignal: true, text: title
            } : null);

            results.push({
                source:           isNegative ? 'NEWS_NEGATIVE' : 'NEWS',
                sourceTier:       'medium',
                tierWeight:       0.6,
                text:             title,
                url:              rssUrl,
                dateIssued:       new Date().toISOString().slice(0, 10),
                relevantPillars:  isNegative ? SOURCE_PILLAR_MAP.NEWS_NEGATIVE : SOURCE_PILLAR_MAP.NEWS,
                criterionSpecificFor: [],
                evidenceType:     'external',
                role:             isNegative ? 'contradicts' : 'supports',
                isNegativeSignal: isNegative,
                negativeTier:     signal ? signal.severity : null,
                flagForReview:    isNegative,
            });
        });
    } catch (err) {
        console.log('[HAI] News signal fetch failed:', err.message);
    }
    return results;
}

// ── Criterion keyword mapper ────────────────────────────────────────────────
// Returns an array of criterion IDs that match keywords in the given text,
// constrained to criteria within the allowed pillars.
function mapTextToCriteria(text, allowedPillars) {
    if (!text) return [];
    const _lower  = text.toLowerCase();
    const matched = [];

    Object.entries(CRITERION_KEYWORD_MAP).forEach(([critId, keywords]) => {
        // Only consider criteria in the allowed pillars
        const pillarId = critId.split('_')[0];
        if (!allowedPillars.includes(pillarId)) return;

        const hasMatch = keywords.some(kw => _lower.includes(kw.toLowerCase()));
        if (hasMatch) matched.push(critId);
    });

    return matched;
}

// ── Admissibility check ─────────────────────────────────────────────────────
// Returns whether an evidence item is admissible for a specific criterion,
// and what role it should have (justifies vs supports).
function checkAdmissibility(item, criterionId) {
    const pillarId  = criterionId.split('_')[0];
    const tier      = (item.sourceTier || '').toLowerCase();
    const isSpecific = (item.criterionSpecificFor || []).includes(criterionId);
    const inPillar  = (item.relevantPillars || []).includes(pillarId);

    if (!inPillar) return { admitted: false };

    if (tier === 'high') {
        // High trust: admitted ONLY if criterion-specific. Role = Justifies.
        if (!isSpecific) return { admitted: false };
        return { admitted: true, role: 'justifies' };
    }

    if (tier === 'medium') {
        // Medium trust: admitted if criterion-specific (justifies) OR pillar-level (supports)
        const role = isSpecific ? 'justifies' : 'supports';
        return { admitted: true, role };
    }

    if (tier === 'low') {
        // Low trust: admitted ONLY if criterion-specific. Role always = Supports.
        // Wayback exception: always supports, never justifies
        if (!isSpecific && item.source !== 'WAYBACK') return { admitted: false };
        return { admitted: true, role: 'supports' };
    }

    return { admitted: false };
}

// ── Maturity gate rules ─────────────────────────────────────────────────────
function computeMaturityGate(criterionId, admittedItems) {
    if (!admittedItems || admittedItems.length === 0) {
        return { maxSupportableLevel: 1, gateReason: 'No admissible evidence', evidenceUsed: [] };
    }

    const highItems   = admittedItems.filter(i => i.sourceTier === 'high' && i.role === 'justifies');
    const medItems    = admittedItems.filter(i => i.sourceTier === 'medium');
    const corroborated = new Set(admittedItems.map(i => i.source)).size >= 2;

    // Level 5: HIGH trust + criterion-specific + corroborated (2+ independent sources)
    if (highItems.length > 0 && corroborated) {
        return { maxSupportableLevel: 5, gateReason: 'High-trust criterion-specific evidence, corroborated', evidenceUsed: admittedItems };
    }
    // Level 4: HIGH trust + criterion-specific (no corroboration required)
    if (highItems.length > 0) {
        return { maxSupportableLevel: 4, gateReason: 'High-trust criterion-specific evidence', evidenceUsed: highItems };
    }
    // Level 3: MEDIUM trust OR (criterion-specific + corroborated)
    if (medItems.length > 0 || corroborated) {
        return { maxSupportableLevel: 3, gateReason: 'Medium-trust evidence or corroborated criterion-specific evidence', evidenceUsed: admittedItems };
    }
    // Level 2: any single admissible evidence item
    return { maxSupportableLevel: 2, gateReason: 'Single admissible evidence item', evidenceUsed: admittedItems };
}

// ── Phase 6 confidence formula ─────────────────────────────────────────────
// Replaces Phase 4 flat formula with materiality × evidence type × time decay.
function computeCriterionConfidence(criterionId, evidenceItems) {
    if (!evidenceItems || evidenceItems.length === 0) return 0;

    let totalContribution = 0;
    evidenceItems.forEach(item => {
        if (item.role === 'contradicts') return;
        totalContribution += computeWeightedContribution(item, criterionId);
    });

    // Corroboration bonus — scaled by materiality
    const uniqueSources = new Set(evidenceItems.map(i => i.source)).size;
    let corrobBonus = 0;
    if (uniqueSources >= 3)      corrobBonus = 15;
    else if (uniqueSources >= 2) corrobBonus = 8;

    const mat         = getMaterialityWeight(criterionId);
    const scaledBonus = Math.round(corrobBonus * mat);

    // Execution bonus from FIX-12
    const execLevel = evidenceItems[0]?.executionLevel || 'none';
    const execBon   = executionBonus(execLevel);

    return Math.min(100, Math.max(0, Math.round(totalContribution + scaledBonus + execBon)));
}

// ── Main export: fetchSupplementaryEvidence ─────────────────────────────────
async function fetchSupplementaryEvidence(companyName, companyUrl, industry, options) {
    options = options || {};
    const combinedText  = options.combinedText  || '';
    const entityProfile = options.entityProfile  || null;

    // ── Fetch all sources in parallel (where safe) ────────────────────────
    console.log('[HAI:supp] Fetching supplementary evidence for:', companyName);

    const [edgarResults, oecdResults, academicResults, wikiMeta, newsResults] = await Promise.all([
        fetchEdgar(companyName).catch(e => { console.log('[HAI:supp] EDGAR error:', e.message); return []; }),
        fetchOecd(companyName).catch(e  => { console.log('[HAI:supp] OECD error:', e.message);  return []; }),
        fetchAcademic(companyName).catch(e => { console.log('[HAI:supp] Academic error:', e.message); return []; }),
        fetchWikipediaMeta(companyName).catch(() => ({ isPublicCompany: false })),
        fetchNewsSignals(companyName).catch(e => { console.log('[HAI:supp] News error:', e.message); return []; }),
    ]);

    // Sequential sources (rate-limit sensitive)
    let waybackResults = [];
    let githubResults  = [];

    try { waybackResults = await fetchWayback(companyUrl); }
    catch (e) { console.log('[HAI:supp] Wayback error:', e.message); }

    try { githubResults  = await fetchGithub(companyName); }
    catch (e) { console.log('[HAI:supp] GitHub error:', e.message); }

    // ── Assemble all evidence ─────────────────────────────────────────────
    let allEvidence = [
        ...edgarResults,
        ...oecdResults,
        ...academicResults,
        ...newsResults,
        ...waybackResults,
        ...githubResults,
    ];

    // ── Phase 6: annotate with time decay and execution detection ─────────
    allEvidence = annotateWithTimeDecay(allEvidence);
    allEvidence = annotateWithExecutionScore(allEvidence, combinedText);

    console.log(`[HAI:supp] Total evidence items after annotation: ${allEvidence.length}`);

    // ── Build criterion evidence map ──────────────────────────────────────
    const criterionEvidence  = {};  // criterionId → [admitted items with role]
    const maturityGates      = {};  // criterionId → gate object
    const criterionConfidence = {};  // criterionId → 0–100

    RUBRIC_DEF.pillars.forEach(pillar => {
        pillar.criteria.forEach(criterion => {
            const critId = criterion.id;
            const admittedItems = [];

            allEvidence.forEach(item => {
                const { admitted, role } = checkAdmissibility(item, critId);
                if (admitted) {
                    admittedItems.push({ ...item, role });
                }
            });

            criterionEvidence[critId]   = admittedItems;
            maturityGates[critId]       = computeMaturityGate(critId, admittedItems);
            criterionConfidence[critId] = computeCriterionConfidence(critId, admittedItems);
        });
    });

    // ── Determine overall tier ────────────────────────────────────────────
    const hasHighTrust   = allEvidence.some(i => i.sourceTier === 'high');
    const hasMediumTrust = allEvidence.some(i => i.sourceTier === 'medium');
    const overallTier    = hasHighTrust ? 'high' : hasMediumTrust ? 'medium' : (allEvidence.length > 0 ? 'low' : 'none');

    // ── Identify criteria capped by maturity gates ────────────────────────
    const cappedCriteria = [];
    // (Actual capping happens frontend-side in Step 2a of updateDashboard)

    // ── Phase 6: Apply negative signal overrides ──────────────────────────
    // Negative override logic operates on the evidence to produce override instructions
    // for the frontend. The override log is returned in impact so the frontend can
    // apply the level reductions in Step 2b of updateDashboard.
    const negativeItems = allEvidence.filter(i => i.role === 'contradicts' || i.isNegativeSignal);
    let overrideLog   = [];
    let hasOverrides  = false;
    let worstSeverity = null;

    if (negativeItems.length > 0) {
        // Build a proxy assessmentState for override calculation
        // (uses maturity gate maxSupportableLevel as proxy for current level)
        const proxyState = {};
        RUBRIC_DEF.pillars.forEach(pillar => {
            pillar.criteria.forEach(c => {
                proxyState[c.id] = { level: maturityGates[c.id]?.maxSupportableLevel || 1, items: [] };
            });
        });

        try {
            const overrideResult = applyNegativeOverrides(proxyState, allEvidence, RUBRIC_DEF);
            overrideLog   = overrideResult.overrideLog   || [];
            hasOverrides  = overrideResult.hasOverrides  || false;
            worstSeverity = overrideResult.worstSeverity || null;
            if (overrideLog.length > 0) {
                console.log(`[HAI:supp] Override adjustments computed: ${overrideLog.length} criteria. Worst severity: ${worstSeverity}`);
            }
        } catch (overrideErr) {
            console.warn('[HAI:supp] Override calculation failed (non-blocking):', overrideErr.message);
        }
    }

    // ── Compute freshness metrics ─────────────────────────────────────────
    const decayedItems = allEvidence.filter(i => i.timeDecayMultiplier !== undefined);
    const avgFreshness = decayedItems.length > 0
        ? Math.round(decayedItems.reduce((s, i) => s + i.timeDecayMultiplier, 0) / decayedItems.length * 100)
        : null;
    const staleCount   = decayedItems.filter(i => i.timeDecayMultiplier < 0.4).length;
    const currentCount = decayedItems.filter(i => i.timeDecayMultiplier >= 0.8).length;
    const activeCertCount = allEvidence.filter(i => i.isCertActive).length;

    // ── Execution gap metrics ─────────────────────────────────────────────
    const verifiedExecCount = allEvidence.filter(i => i.executionLevel === 'verified').length;
    const execGapCriteria   = [];
    RUBRIC_DEF.pillars.forEach(pillar => {
        pillar.criteria.forEach(c => {
            const items = criterionEvidence[c.id] || [];
            const hasPolicy    = items.some(i => i.evidenceType === 'governance');
            const hasExecution = items.some(i => i.executionLevel === 'verified' || i.executionLevel === 'partial');
            if (hasPolicy && !hasExecution) execGapCriteria.push(c.id);
        });
    });

    // ── Assemble impact object ────────────────────────────────────────────
    const impact = {
        criterionEvidence,
        maturityGates,
        criterionConfidence,
        overallTier,
        hasHighTrustEvidence: hasHighTrust,
        cappedCriteria,
        traceability:         allEvidence,
        sourceCounts: {
            EDGAR:    edgarResults.length,
            OECD:     oecdResults.length,
            ACADEMIC: academicResults.length,
            NEWS:     newsResults.filter(i => !i.isNegativeSignal).length,
            NEWS_NEGATIVE: newsResults.filter(i => i.isNegativeSignal).length,
            GITHUB:   githubResults.length,
            WAYBACK:  waybackResults.length,
        },
        // Phase 6: override instructions for frontend Step 2b
        negativeOverrides:  overrideLog,
        hasOverrides,
        worstSeverity,
        // Phase 6: freshness
        avgFreshness,
        staleEvidenceCount:   staleCount,
        currentEvidenceCount: currentCount,
        activeCertCount,
        // Phase 6: execution
        executionGapCount:        execGapCriteria.length,
        verifiedExecutionCount:   verifiedExecCount,
        executionGapCriteria,
    };

    // ── Return supplementary_signals shape (matches frontend expectations) ─
    return {
        impact,
        edgarSignals:    edgarResults.length,
        waybackSignals:  waybackResults.length,
        oecdSignals:     oecdResults.length,
        githubSignals:   githubResults.length,
        academicSignals: academicResults.length,
        newsSignals:     newsResults.filter(i => !i.isNegativeSignal).length,
        negativeSignals: newsResults.filter(i => i.isNegativeSignal).length,
        totalSignals:    allEvidence.length,
        isPublicCompany: wikiMeta.isPublicCompany || entityProfile?.isPublicCompany || false,
        evidence:        allEvidence,
        sourceBreakdown: impact.sourceCounts,
    };
}

module.exports = { fetchSupplementaryEvidence };
