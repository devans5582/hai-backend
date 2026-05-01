'use strict';

const axios = require('axios');

// ---------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------
const OPENAI_API_URL    = 'https://api.openai.com/v1/chat/completions';
const OPENAI_MODEL      = 'gpt-4o';
const OPENAI_TEMP       = 0.3;
const OPENAI_TIMEOUT_MS = 60000;

// ---------------------------------------------------------------
// System prompt — unchanged from approved Phase 3 specification.
// Snapshot fields are returned null; frontend populates them from
// exact client-side score calculations.
// ---------------------------------------------------------------
const SYSTEM_PROMPT = `You are generating a Humaital Human-Alignment Index (HAI) Premium Evaluation Report.

This output will be used in a web UI and a formal PDF report. It must be clear, structured, concise, and actionable.

You are NOT writing a narrative article.
You ARE generating a structured evaluation report.

-------------------------------------
CRITICAL RULES (DO NOT VIOLATE)
-------------------------------------

- Use plain English (5th\u20138th grade reading level)
- Keep sentences short (under 20 words when possible)
- Do NOT use jargon or technical language
- Do NOT use vague corporate phrases
- Do NOT exaggerate or speculate
- Every issue must include a clear action
- Every pillar must include a next step
- Tone must be calm, neutral, and professional
- Do NOT sound like marketing
- Do NOT write long paragraphs

-------------------------------------
OUTPUT FORMAT (MANDATORY)
-------------------------------------

Return ONLY a valid JSON object. No markdown. No explanation. No text outside the JSON.

The snapshot object MUST have all four keys set to null. Do not fill them in.
The frontend will populate them from verified score calculations.

{
  "executive_summary": "",
  "score_interpretation": "",
  "snapshot": {
    "alignment_level": null,
    "evidence_strength": null,
    "certification_status": null,
    "benchmark_position": null
  },
  "pillars": [
    {
      "pillar_name": "",
      "status_label": "",
      "what_we_found": "",
      "why_it_matters": "",
      "next_step": ""
    }
  ],
  "strengths": [
    {
      "title": "",
      "explanation": "",
      "why_it_matters": ""
    }
  ],
  "improvement_areas": [
    {
      "title": "",
      "what_we_found": "",
      "why_it_matters": "",
      "what_to_do_next": ""
    }
  ],
  "action_plan": {
    "immediate_actions": [],
    "near_term_improvements": [],
    "long_term_strengthening": []
  },
  "confidence_explanation": "",
  "evidence_summary": {
    "core_governance": "",
    "operational_evidence": "",
    "external_validation": "",
    "summary": ""
  },
  "certification_statement": ""
}

-------------------------------------
SECTION REQUIREMENTS
-------------------------------------

EXECUTIVE SUMMARY:
- 2\u20133 sentences
- Describe overall alignment direction and evidence quality based on what was found
- Do NOT reference a score number \u2014 the snapshot will carry score context

SCORE INTERPRETATION:
- Max 4 sentences
- Explain what the HAI Score and Evidence Strength mean in plain language
- Do NOT invent score numbers

SNAPSHOT:
- All four fields must be null \u2014 do not fill them in

PILLARS:
- Exactly 6 pillars in this order: Trust, Accountability, Purpose, Safety, Transparency, Impact
- Each must include:
  - status_label: one of: Strong | Progressing | Developing | Needs Attention
  - what_we_found: 1\u20132 short sentences based on the criterion levels and evidence provided
  - why_it_matters: 1 sentence
  - next_step: 1 sentence starting with an action verb

STRENGTHS:
- 2\u20133 items minimum
- Must be grounded in the evidence data provided

IMPROVEMENT AREAS:
- 3\u20135 items
- Each must include what_we_found, why_it_matters, what_to_do_next
- what_to_do_next must start with an action verb
- No sentence over 20 words

ACTION PLAN:
- immediate_actions: 0\u201330 days
- near_term_improvements: 30\u201390 days
- long_term_strengthening: 90+ days
- Each item is a plain string \u2014 clear and practical

CONFIDENCE EXPLANATION:
- 3\u20134 sentences
- Must explain that confidence reflects evidence visibility, not internal practice quality

EVIDENCE SUMMARY:
- core_governance: one of: Strong | Emerging | Limited | None
- operational_evidence: one of: Strong | Emerging | Limited | None
- external_validation: one of: Strong | Limited | None
- summary: 1 short sentence

CERTIFICATION STATEMENT:
- 2\u20133 sentences
- Neutral and professional
- Must reflect readiness direction and encourage improvement

-------------------------------------
WRITING STYLE RULES
-------------------------------------

ALWAYS USE:
- "We found..."
- "This matters because..."
- "A strong next step is..."

AVOID:
- "robust framework"
- "holistic system"
- "cross-functional maturity"
- "leverage"
- "synergies"
- "suboptimal"
- "no evidence found" (say what WAS found instead)
- "limited across all areas" (describe specific gaps instead)
- "no governance" or "absence of governance" (when any evidence exists)
- "governance signals" or "strong signals" or "high-value signals" (use evidence-based language)
- "signals are present" or "signals identified" or "signals detected" (say what the evidence shows)
- "signals indicate" (say "publicly available documentation supports" or "evidence shows" instead)

EVIDENCE-QUALITY NARRATIVE RULES (MANDATORY):
- The executive_summary MUST describe what evidence was found and what it supports — not how many signals were detected.
- Use evidence-quality language: "publicly available evidence supports foundational governance practices" not "governance signals are present."
- evidence_summary.summary must use the evidence tier language from the interpretation frame in the user prompt. Do NOT use "signals identified" phrasing — use "evidence found" or "documentation available."
- The certification_statement must reflect actual evidence tier and credibility, not signal counts.
- Never use the word "signals" in executive_summary, confidence_explanation, or certification_statement.

-------------------------------------
FINAL VALIDATION (MANDATORY)
-------------------------------------

Before returning:
- Ensure ALL sections are present
- Ensure snapshot has all four keys set to null
- Ensure JSON is valid
- Ensure no text outside the JSON object
- Ensure every improvement area has what_to_do_next
- Ensure every pillar has a next_step
- Ensure language is simple and clear
- Ensure narrative language reflects evidence quality, not signal counts
- Ensure pillars marked [SIGNAL PRESENT] have status_label of "Developing" or better
- Ensure executive_summary, confidence_explanation, and certification_statement do NOT use the word "signals"`;


// ---------------------------------------------------------------
// GOVERNANCE SIGNAL DETECTION
// ---------------------------------------------------------------

// ---------------------------------------------------------------
// TEXT-BODY patterns — match governance language in page content.
// Separators are [\s\-_] so "responsible-ai", "responsible ai",
// and "responsible_ai" all match.
// ---------------------------------------------------------------

// HIGH: AI-specific governance language
const HIGH_TEXT_PATTERNS = [
    /responsible[\s\-_]ai/i,
    /ai[\s\-_]principles/i,
    /ai[\s\-_]governance/i,
    /governance[\s\-_]framework/i,
    /ai[\s\-_]ethics/i,
    /ethical[\s\-_]ai/i,
    /ai[\s\-_]safety/i,
    /safety[\s\-_]framework/i,
    /ai[\s\-_]policy/i,
    /human[\s\-_]?alignment/i,
    /trustworthy[\s\-_]ai/i,
    /responsible[\s\-_]technology/i,
    /ai[\s\-_]accountability/i,
];

// MEDIUM: Structured transparency and AI-adjacent governance language
const MEDIUM_TEXT_PATTERNS = [
    /trust[\s\-_]cent(?:er|re)/i,
    /transparency[\s\-_]report/i,
    /transparency[\s\-_]disclosure/i,
    /public[\s\-_]commitment/i,
    /governance[\s\-_]disclosure/i,
    /data[\s\-_]governance/i,
    /algorithmic[\s\-_]accountability/i,
    /model[\s\-_]card/i,
    /system[\s\-_]card/i,
    /impact[\s\-_]assessment/i,
    /risk[\s\-_]management[\s\-_]framework/i,
];

// ENTERPRISE: Non-AI governance signals common in regulated industries.
// These count toward medium_signals — enough to pass the evaluation gate
// and earn Tier-1 uplift, but AI-specific signals still earn higher tiers.
// Rationale: a company with internal controls, audit committees, and risk
// frameworks has meaningful governance infrastructure even without an
// explicit AI policy. Enterprise governance should not return "No Score".
const ENTERPRISE_TEXT_PATTERNS = [
    // Accountability / oversight
    /(?:audit|risk|governance)[\s\-_]committee/i,
    /board[\s\-_](?:oversight|governance|committee)/i,
    /internal[\s\-_]controls?/i,
    /operational[\s\-_](?:oversight|resilience|risk)/i,
    /enterprise[\s\-_](?:risk|governance|compliance)/i,
    /(?:risk|compliance)[\s\-_](?:framework|program|management)/i,
    /regulatory[\s\-_]compliance/i,
    /sox[\s\-_]compliance|sarbanes.oxley/i,

    // Safety and incident prevention
    /safety[\s\-_]protocols?/i,
    /incident[\s\-_](?:prevention|management|response)[\s\-_](?:plan|policy|framework)/i,
    /business[\s\-_]continuity/i,
    /disaster[\s\-_]recovery/i,
    /cybersecurity[\s\-_](?:framework|program|policy|resilience)/i,
    /information[\s\-_]security[\s\-_](?:policy|framework|program)/i,

    // Transparency and reporting
    /esg[\s\-_](?:report|disclosure|framework|commitment)/i,
    /sustainability[\s\-_]report/i,
    /corporate[\s\-_](?:governance|responsibility)[\s\-_]report/i,
    /annual[\s\-_]report/i,
    /proxy[\s\-_]statement/i,

    // Purpose and mission alignment
    /(?:corporate|social)[\s\-_]responsibility/i,
    /ethical[\s\-_](?:sourcing|conduct|standards?|principles?)/i,
    /code[\s\-_]of[\s\-_](?:conduct|ethics)/i,
    /human[\s\-_]rights[\s\-_](?:policy|commitment|statement)/i,
    /diversity[\s\-_](?:equity|inclusion|and)/i,

    // Impact measurement
    /measurable[\s\-_]impact/i,
    /community[\s\-_](?:investment|impact|initiative)/i,
    /stakeholder[\s\-_]engagement/i,
    /whistleblower[\s\-_](?:policy|program|hotline)/i,
];

const LOW_TEXT_PATTERNS = [
    /privacy[\s\-_]policy/i,
    /terms[\s\-_]of[\s\-_](use|service)/i,
    /cookie[\s\-_]policy/i,
    /legal[\s\-_]notice/i,
    /disclaimer/i,
    /copyright[\s\-_]notice/i,
];

// ---------------------------------------------------------------
// URL-SLUG patterns — classify URLs from section headers.
// The scraper emits "--- Content from URL ---" headers even when
// a page body is blocked or empty.
// ---------------------------------------------------------------

const HIGH_URL_SLUGS = [
    'responsible-ai', 'responsible_ai',
    'ai-policy',      'ai_policy',
    'ai-principles',  'ai_principles',
    'ai-ethics',      'ai_ethics',
    '/ethics',
    'ai-governance',  'ai_governance',
    '/governance',
    'ai-safety',      'ai_safety',
    '/responsible',
    'human-alignment','human_alignment',
];

const MEDIUM_URL_SLUGS = [
    '/trust',         'trust-center',  'trustcenter',
    '/transparency',  'transparency-report',
    '/responsibility',
    '/security',
    '/compliance',
];

// Enterprise URL slugs — count as medium_signals
const ENTERPRISE_URL_SLUGS = [
    '/esg',           'esg-report',     'esg-disclosure',
    '/sustainability','sustainability-report',
    '/risk',          'risk-management','enterprise-risk',
    '/governance',    'corporate-governance',
    '/audit',         'internal-audit',
    '/compliance',    'regulatory-compliance',
    '/cybersecurity', 'information-security',
    '/csr',           'corporate-responsibility',
    '/dei',           'diversity-equity',
    '/ethics',        'code-of-conduct', 'code-of-ethics',
    '/annual-report', '/proxy',
    '/investor-relations',
    '/safety',        'health-and-safety',
    '/whistleblower', 'speak-up',
    '/human-rights',
];

const LOW_URL_SLUGS = [
    '/privacy', '/terms', '/legal', '/cookie', '/disclaimer',
];

// ---------------------------------------------------------------
// detectGovernanceSignals
//
// Two-pass detection:
//   Pass 1 — extract URLs from section headers and classify slugs
//   Pass 2 — run text-body patterns against full combined_text
//
// A signal is counted ONCE per unique pattern/slug match.
// A URL and a body-text match for the same concept count as one
// hit (URL wins first; text patterns skip if already matched).
// This prevents double-counting "responsible-ai" URL + body text.
// ---------------------------------------------------------------
function detectGovernanceSignals(scrapedText) {
    if (!scrapedText || typeof scrapedText !== 'string') {
        return { high_signals: 0, medium_signals: 0, low_signals: 0, enterprise_signals: 0, matched_phrases: [] };
    }

    const matched = [];
    let high = 0, medium = 0, low = 0, enterprise = 0;

    // ── Pass 1: URL slug classification ──────────────────────────
    const urls = [];
    const urlHeaderRe = /---\s*Content from\s+(https?:\/\/\S+?)\s*---/gi;
    let m;
    while ((m = urlHeaderRe.exec(scrapedText)) !== null) {
        urls.push(m[1].toLowerCase());
    }

    const urlMatchedConcepts = new Set();

    for (const url of urls) {
        // High: AI-specific slugs
        for (const slug of HIGH_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('high:' + slug)) {
                urlMatchedConcepts.add('high:' + slug);
                high++;
                matched.push({ tier: 'high', phrase: slug + ' (url)', source: 'url' });
                break;
            }
        }
        // Medium: structured transparency slugs
        for (const slug of MEDIUM_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('medium:' + slug)) {
                urlMatchedConcepts.add('medium:' + slug);
                medium++;
                matched.push({ tier: 'medium', phrase: slug + ' (url)', source: 'url' });
                break;
            }
        }
        // Enterprise: non-AI governance slugs (counts toward medium_signals)
        for (const slug of ENTERPRISE_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('enterprise:' + slug)) {
                urlMatchedConcepts.add('enterprise:' + slug);
                enterprise++;
                medium++;  // enterprise signals count as medium so evaluation gate passes
                matched.push({ tier: 'enterprise', phrase: slug + ' (url)', source: 'url' });
                break;
            }
        }
        // Low: generic legal slugs
        for (const slug of LOW_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('low:' + slug)) {
                urlMatchedConcepts.add('low:' + slug);
                low++;
                matched.push({ tier: 'low', phrase: slug + ' (url)', source: 'url' });
                break;
            }
        }
    }

    // ── Pass 2: text-body pattern matching ───────────────────────
    for (const p of HIGH_TEXT_PATTERNS) {
        const hit = scrapedText.match(p);
        if (hit) {
            const phrase = hit[0].trim().toLowerCase();
            const alreadyCounted = matched.some(
                x => x.tier === 'high' && x.source === 'url' &&
                     phrase.replace(/[\s_]/g, '-').includes(x.phrase.replace(' (url)', ''))
            );
            if (!alreadyCounted) {
                high++;
                matched.push({ tier: 'high', phrase, source: 'text' });
            }
        }
    }
    for (const p of MEDIUM_TEXT_PATTERNS) {
        const hit = scrapedText.match(p);
        if (hit) {
            const phrase = hit[0].trim().toLowerCase();
            const alreadyCounted = matched.some(x =>
                (x.tier === 'medium' || x.tier === 'enterprise') && x.source === 'url' &&
                phrase.replace(/[\s_]/g, '-').includes(x.phrase.replace(' (url)', '')));
            if (!alreadyCounted) {
                medium++;
                matched.push({ tier: 'medium', phrase, source: 'text' });
            }
        }
    }
    // Enterprise text patterns — each unique match counts as medium
    const seenEnterprise = new Set();
    for (const p of ENTERPRISE_TEXT_PATTERNS) {
        const hit = scrapedText.match(p);
        if (hit) {
            const phrase = hit[0].trim().toLowerCase();
            if (!seenEnterprise.has(phrase)) {
                seenEnterprise.add(phrase);
                // Only count if not already captured by URL pass
                const alreadyCounted = matched.some(x => x.tier === 'enterprise' &&
                    x.source === 'url' && phrase.replace(/[\s_]/g, '-').includes(
                        x.phrase.replace(' (url)', '')));
                if (!alreadyCounted) {
                    enterprise++;
                    medium++;  // enterprise signals count as medium
                    matched.push({ tier: 'enterprise', phrase, source: 'text' });
                }
            }
        }
    }
    for (const p of LOW_TEXT_PATTERNS) {
        const hit = scrapedText.match(p);
        if (hit) {
            const phrase = hit[0].trim().toLowerCase();
            const alreadyCounted = matched.some(x => x.tier === 'low' && x.source === 'url' &&
                phrase.replace(/[\s_]/g, '-').includes(x.phrase.replace(' (url)', '')));
            if (!alreadyCounted) {
                low++;
                matched.push({ tier: 'low', phrase, source: 'text' });
            }
        }
    }

    return {
        high_signals:       high,
        medium_signals:     medium,  // includes enterprise contributions
        low_signals:        low,
        enterprise_signals: enterprise,
        matched_phrases:    matched
    };
}


// ---------------------------------------------------------------
// EVALUATION STATE
// ---------------------------------------------------------------
function determineEvaluationState(signals, isPartial) {
    if (signals.high_signals === 0 && signals.medium_signals === 0) {
        return 'insufficient_evidence';
    }
    // partial_evaluation: signals detected but scraping was incomplete.
    // Scoring proceeds but confidence is lowered in the narrative.
    if (isPartial) {
        return 'partial_evaluation';
    }
    return 'valid';
}


// ---------------------------------------------------------------
// INSUFFICIENT EVIDENCE RESPONSE
// ---------------------------------------------------------------

const PILLAR_MISSING_EVIDENCE = {
    Trust:          { description: 'No public AI ethics, principles, or trust commitments found.',          examples: ['AI principles page', 'Responsible AI statement', 'User trust commitments'] },
    Accountability: { description: 'No governance structure or accountability disclosures detected.',       examples: ['Governance charter', 'Named AI accountability owner', 'Incident response policy'] },
    Purpose:        { description: 'No mission alignment or human-centered intent signals found.',          examples: ['AI mission statement', 'Human impact policy', 'Purpose-driven AI commitments'] },
    Safety:         { description: 'No AI safety framework or risk management content detected.',           examples: ['AI safety policy', 'Risk assessment framework', 'Red-teaming or safety testing references'] },
    Transparency:   { description: 'No transparency disclosures or explainability commitments found.',     examples: ['Transparency report', 'Model cards', 'Data disclosure policy'] },
    Impact:         { description: 'No outcome measurement or societal impact content detected.',           examples: ['Impact metrics', 'Community benefit statements', 'Sustainability commitments'] }
};

function buildInsufficientEvidenceResponse(signals) {
    return {
        evaluation_state: 'insufficient_evidence',
        reason: 'Insufficient publicly available governance documentation was found to produce a verified HAI Score. Publishing governance policies, AI principles, or responsibility frameworks would enable a full assessment.',
        signal_profile: { high_signals: signals.high_signals, medium_signals: signals.medium_signals, low_signals: signals.low_signals },
        missing_evidence: PILLAR_MISSING_EVIDENCE,
        recommended_next_steps: {
            immediate:  ['Publish a Responsible AI or AI Principles page on your public website.', 'Add an AI governance or AI ethics section to your corporate policies.'],
            near_term:  ['Publish a transparency report or AI use policy.', 'Create a dedicated trust center linking all governance documents.'],
            long_term:  ['Establish a formal AI governance framework covering all six HAI pillars.', 'Commission an independent AI audit and publish key findings.']
        }
    };
}


// ---------------------------------------------------------------
// SIGNAL TIER CLASSIFICATION
// ---------------------------------------------------------------

const _PILLAR_CRITERIA = {
    Trust:          ['trust_user_confidence','trust_consistency_of_behavior','trust_ethical_intent','trust_absence_of_manipulation'],
    Accountability: ['accountability_ownership_of_outcomes','accountability_corrective_action','accountability_governance_and_oversight'],
    Purpose:        ['purpose_mission_clarity','purpose_human_centered_intent','purpose_alignment_words_actions'],
    Safety:         ['safety_risk_mitigation','safety_user_protection_mechanisms','safety_long_term_societal_safety'],
    Transparency:   ['transparency_explainability','transparency_data_disclosure','transparency_communication_honesty'],
    Impact:         ['impact_positive_human_outcomes','impact_shared_human_benefit','impact_measurability_of_impact','impact_durability_of_impact']
};

function countPillarsWithEvidence(evaluationData) {
    let count = 0;
    for (const criteriaIds of Object.values(_PILLAR_CRITERIA)) {
        const has = criteriaIds.some(id => {
            const c = evaluationData[id];
            return c && Array.isArray(c.items) && c.items.length > 0;
        });
        if (has) count++;
    }
    return count;
}

function classifySignalTier(signals, evaluationData, confPercent) {
    const { high_signals, medium_signals } = signals;
    const pillarsWithEvidence = countPillarsWithEvidence(evaluationData);

    // Tier 4: high signals AND broad pillar coverage
    // Tier 3.5 downgrade: qualifies for Tier4 by signal count but confidence is low,
    // suggesting URL slugs exist without confirmed deep body evidence.
    // Treated as Tier3 for uplift; multi-pillar bonus suppressed.
    if (high_signals >= 4 && pillarsWithEvidence >= 4) {
        const conf = typeof confPercent === 'number' ? confPercent : 100;
        if (conf < EVIDENCE_CAP_THRESHOLD) {
            return { tier: 3, pillarsWithEvidence, downgraded: true };
        }
        return { tier: 4, pillarsWithEvidence, downgraded: false };
    }
    if (high_signals >= 3) return { tier: 3, pillarsWithEvidence, downgraded: false };
    if (high_signals >= 1) return { tier: 2, pillarsWithEvidence, downgraded: false };
    if (medium_signals >= 1) return { tier: 1, pillarsWithEvidence, downgraded: false };
    return { tier: 0, pillarsWithEvidence, downgraded: false };
}


// ---------------------------------------------------------------
// CALIBRATION (BOUNDED UPLIFT)
// ---------------------------------------------------------------

// Uplift midpoints by tier — calibrated so strong governance companies
// (Tier 3-4) land meaningfully above weak companies after uplift.
// These apply to the frontend's exact claimedScore as the base.
// Tier ranges: Tier1=+3–7, Tier2=+10–20, Tier3=+22–35, Tier4=+25–45
// Tier4 midpoint reduced (42→35) so high-signal companies with strong conf
// score meaningfully but don't over-inflate relative to evidence depth.
const UPLIFT_MIDPOINTS = { 1: 5, 2: 15, 3: 29, 4: 35 };
const SCORE_CAP = 85;

// Evidence-based score cap: prevents high score + low evidence contradiction.
// Applied when exact confPercent is available (frontend) and when proxy is used (backend).
const EVIDENCE_CAP_THRESHOLD = 70;  // confPercent below this triggers the cap
const EVIDENCE_CAP_VALUE     = 75;  // max score when evidence is below threshold


// ---------------------------------------------------------------
// SIGNAL-TO-PILLAR MAPPING
//
// Maps detected high/medium signal slugs to the HAI pillars they
// most directly support. Used to build the interpretation frame
// that prevents "no evidence" language when signals ARE present.
// ---------------------------------------------------------------
const SIGNAL_TO_PILLAR = {
    // High-value URL slugs
    'responsible-ai':   ['Trust', 'Accountability', 'Purpose'],
    'ai-principles':    ['Trust', 'Accountability', 'Purpose'],
    'ai-ethics':        ['Trust', 'Purpose'],
    '/ethics':          ['Trust', 'Purpose'],
    'ai-governance':    ['Accountability', 'Transparency'],
    '/governance':      ['Accountability', 'Transparency'],
    'ai-policy':        ['Accountability', 'Transparency'],
    'ai-safety':        ['Safety'],
    '/responsible':     ['Trust', 'Accountability'],
    'human-alignment':  ['Trust', 'Purpose', 'Impact'],
    // Medium-value URL slugs
    '/trust':           ['Trust'],
    'trust-center':     ['Trust', 'Transparency'],
    '/transparency':    ['Transparency'],
    'transparency-report': ['Transparency'],
    '/security':        ['Safety', 'Trust'],
    '/compliance':      ['Accountability'],
    '/responsibility':  ['Accountability', 'Purpose'],
    // Text-body phrases (normalised)
    'responsible ai':   ['Trust', 'Accountability', 'Purpose'],
    'ai principles':    ['Trust', 'Accountability'],
    'ai governance':    ['Accountability', 'Transparency'],
    'governance framework': ['Accountability'],
    'ai ethics':        ['Trust', 'Purpose'],
    'ethical ai':       ['Trust', 'Purpose'],
    'ai safety':        ['Safety'],
    'ai policy':        ['Accountability', 'Transparency'],
    'human alignment':  ['Trust', 'Purpose', 'Impact'],
    'transparency report': ['Transparency'],
    'data governance':  ['Transparency', 'Accountability'],
    'impact assessment': ['Impact'],

    // Enterprise governance → pillar mappings
    // Trust
    '/security':                ['Trust'],
    '/cybersecurity':           ['Trust', 'Safety'],
    'information-security':     ['Trust', 'Safety'],
    'cybersecurity framework':  ['Trust', 'Safety'],
    'data protection':          ['Trust', 'Transparency'],
    // Accountability
    '/audit':                   ['Accountability'],
    'internal-audit':           ['Accountability'],
    'audit committee':          ['Accountability'],
    'risk committee':           ['Accountability'],
    'governance committee':     ['Accountability'],
    'board oversight':          ['Accountability'],
    'internal controls':        ['Accountability'],
    'enterprise risk':          ['Accountability', 'Safety'],
    '/compliance':              ['Accountability'],
    'regulatory compliance':    ['Accountability'],
    'sox compliance':           ['Accountability'],
    '/whistleblower':           ['Accountability'],
    'speak-up':                 ['Accountability'],
    // Purpose
    '/csr':                     ['Purpose'],
    'corporate responsibility': ['Purpose', 'Impact'],
    'code of conduct':          ['Purpose', 'Accountability'],
    'code of ethics':           ['Purpose', 'Accountability', 'Trust'],
    'ethical sourcing':         ['Purpose'],
    'ethical conduct':          ['Purpose', 'Accountability'],
    'human rights policy':      ['Purpose', 'Impact'],
    '/dei':                     ['Purpose', 'Impact'],
    'diversity equity':         ['Purpose', 'Impact'],
    // Safety
    '/safety':                  ['Safety'],
    '/risk':                    ['Safety', 'Accountability'],
    'risk management':          ['Safety', 'Accountability'],
    'risk-management':          ['Safety', 'Accountability'],
    'safety protocols':         ['Safety'],
    'business continuity':      ['Safety'],
    'disaster recovery':        ['Safety'],
    'incident prevention':      ['Safety'],
    // Transparency
    '/esg':                     ['Transparency', 'Impact'],
    'esg-report':               ['Transparency', 'Impact'],
    'esg disclosure':           ['Transparency'],
    '/sustainability':          ['Transparency', 'Impact'],
    'sustainability-report':    ['Transparency', 'Impact'],
    'annual-report':            ['Transparency'],
    '/proxy':                   ['Transparency', 'Accountability'],
    '/investor-relations':      ['Transparency'],
    'corporate governance report': ['Transparency', 'Accountability'],
    // Impact
    'community investment':     ['Impact'],
    'community impact':         ['Impact'],
    'community-investment':     ['Impact'],
    'measurable impact':        ['Impact'],
    'stakeholder engagement':   ['Impact', 'Purpose'],
    'esg outcomes':             ['Impact'],
    '/human-rights':            ['Impact', 'Purpose'],
};

/**
 * Returns the set of pillar names evidenced by detected signals.
 * A pillar is "evidenced by signals" even when the rubric item count is 0
 * because signals come from URL slugs on blocked pages.
 */
function getPillarsEvidencedBySignals(signalProfile) {
    const pillarSet = new Set();
    if (!signalProfile || !signalProfile.matched_phrases) return pillarSet;
    for (const match of signalProfile.matched_phrases) {
        const key = match.phrase.replace(' (url)', '').replace('[url]', '').trim().toLowerCase();
        const pillars = SIGNAL_TO_PILLAR[key];
        if (pillars) pillars.forEach(p => pillarSet.add(p));
    }
    return pillarSet;
}

/**
 * Returns the tier-appropriate evidence language for use in the prompt.
 * Prevents binary "no evidence" language when signals are present.
 */
function getInterpretationFrame(signalProfile) {
    if (!signalProfile) return null;
    const h = signalProfile.high_signals || 0;
    const m = signalProfile.medium_signals || 0;
    const total = h + m;

    if (h >= 3) {
        return {
            evidence_language: 'Publicly available governance evidence identified',
            pillar_baseline:   'Publicly available governance documentation supports foundational practices, but coverage varies across pillars.',
            forbidden_phrases: ['no evidence found', 'limited across all areas', 'no governance', 'absence of governance', 'governance signals', 'signals identified', 'signals are present', 'signals detected'],
            executive_frame:   'Publicly available evidence supports foundational governance practices. The assessment reflects the scope of documentation accessible at the time of evaluation.',
        };
    }
    if (h >= 1 || m >= 2) {
        return {
            evidence_language: 'Partial governance documentation identified',
            pillar_baseline:   'Some governance documentation is publicly available, but several pillars lack confirmed evidence.',
            forbidden_phrases: ['no evidence found', 'no governance present', 'governance signals', 'signals identified', 'signals detected'],
            executive_frame:   'Partial governance documentation is publicly available. The assessment reflects the scope of evidence accessible, not the totality of governance practices in place.',
        };
    }
    // Enterprise governance only — no AI-specific signals
    const enterpriseCount = (signalProfile.enterprise_signals || 0);
    if (enterpriseCount >= 2) {
        return {
            evidence_language: 'Enterprise governance documentation identified',
            pillar_baseline:   'Foundational enterprise governance documentation is publicly available. AI-specific governance documentation would significantly strengthen this assessment.',
            forbidden_phrases: ['no governance', 'absence of governance', 'no evidence of any governance', 'governance signals', 'signals identified'],
            executive_frame:   'Enterprise governance documentation is publicly available. The assessment reflects the absence of explicit AI-specific documentation, not the absence of governance overall.',
        };
    }
    if (total >= 1) {
        return {
            evidence_language: 'Limited publicly available governance documentation',
            pillar_baseline:   'Minimal governance documentation was identified. Evidence coverage across the six pillars is largely unconfirmed.',
            forbidden_phrases: ['complete absence of governance', 'governance signals', 'signals detected', 'signals identified'],
            executive_frame:   'Limited governance documentation was publicly available at the time of assessment. Publishing additional governance materials would strengthen this evaluation.',
        };
    }
    return null;
}



function computeCalibration(rawScore, tier, pillarsWithEvidence, confPercent, downgraded, signals, scrapeBlocked) {
    if (tier === 0) return { calibrated_score: rawScore, uplift_applied: 0, multi_pillar_bonus: 0, tier, downgraded: false };

    // Base uplift from midpoint, then vary by actual signal depth within the tier
    let uplift = UPLIFT_MIDPOINTS[tier] || 0;

    // Vary uplift within the tier based on high signal count so two Tier-3
    // companies don't always get identical scores:
    //   Tier3 range: 22–35.  midpoint=29.  adjust by ±(highSignals-3)*2 clamped to range.
    //   Tier2 range: 10–20.  midpoint=15.  adjust by ±(highSignals-1)*2.5 clamped.
    if (signals && tier === 3) {
        const delta = Math.min(6, Math.max(-6, ((signals.high_signals || 3) - 3) * 2));
        uplift = Math.round(Math.min(35, Math.max(22, uplift + delta)));
    } else if (signals && tier === 2) {
        const delta = Math.min(5, Math.max(-5, ((signals.high_signals || 1) - 1) * 2.5));
        uplift = Math.round(Math.min(20, Math.max(10, uplift + delta)));
    } else if (signals && tier === 1) {
        const delta = Math.min(2, Math.max(-2, ((signals.medium_signals || 1) - 1)));
        uplift = Math.round(Math.min(7, Math.max(3, uplift + delta)));
    }

    // Scrape-blocked penalty: if website was fully blocked, reduce uplift by 25%
    // since we have less confidence the signals reflect actual page depth.
    if (scrapeBlocked) {
        uplift = Math.round(uplift * 0.75);
    }

    // Confidence modifier: reduce uplift 20% when evidence strength < 50%
    if (typeof confPercent === 'number' && confPercent < 50) {
        uplift = Math.round(uplift * 0.8);
    }

    // Multi-pillar bonus suppressed for Tier3.5 downgrades —
    // the broad coverage exists only at URL-slug level, not confirmed rubric depth.
    const multiPillarBonus = (pillarsWithEvidence >= 4 && !downgraded) ? 8 : 0;

    let finalScore = Math.min(Math.max(rawScore + uplift + multiPillarBonus, 1), SCORE_CAP);

    // Evidence-based cap: prevents high score + low confidence contradiction.
    // Applied here using the proxy confPercent; the frontend re-applies with exact value.
    if (typeof confPercent === 'number' && confPercent < EVIDENCE_CAP_THRESHOLD) {
        finalScore = Math.min(finalScore, EVIDENCE_CAP_VALUE);
    }

    return {
        calibrated_score:   Math.round(finalScore * 10) / 10,
        uplift_applied:     uplift,
        multi_pillar_bonus: multiPillarBonus,
        tier,
        downgraded:         !!downgraded,
        evidence_cap_applied: (typeof confPercent === 'number' && confPercent < EVIDENCE_CAP_THRESHOLD)
    };
}


// ---------------------------------------------------------------
// RAW SCORE PROXY
// ---------------------------------------------------------------
function deriveRawScoreProxy(evaluationData) {
    if (!evaluationData || typeof evaluationData !== 'object') return 0;
    const PILLAR_MAX = { Trust: 20, Accountability: 15, Purpose: 15, Safety: 15, Transparency: 15, Impact: 20 };
    let total = 0;
    for (const [pillarName, criteriaIds] of Object.entries(_PILLAR_CRITERIA)) {
        const maxPoints = PILLAR_MAX[pillarName];
        let ratioSum = 0;
        for (const critId of criteriaIds) {
            const crit  = evaluationData[critId];
            const level = (crit && crit.level) ? Math.min(5, Math.max(1, crit.level)) : 1;
            ratioSum += (level - 1) / 4;
        }
        total += (ratioSum / criteriaIds.length) * maxPoints;
    }
    return Math.round(total * 10) / 10;
}


// ---------------------------------------------------------------
// buildUserPrompt
// ---------------------------------------------------------------
function buildUserPrompt(evaluationData, scrapedText, signalProfile, isPartial) {
    const LEVEL_LABELS = { 1: 'Not Present', 2: 'Initial', 3: 'Developing', 4: 'Established', 5: 'Advanced' };
    let pillarSummaries = '';
    let totalItems = 0, pillarsWithEvidence = 0;

    // Pillars evidenced by URL signals — these must not be described as "no evidence"
    // even when rubric item counts are zero (blocked page bodies).
    const signalEvidencedPillars = getPillarsEvidencedBySignals(signalProfile);
    const frame = getInterpretationFrame(signalProfile);

    for (const [pillarName, criteriaIds] of Object.entries(_PILLAR_CRITERIA)) {
        const pillarHasSignal = signalEvidencedPillars.has(pillarName);
        pillarSummaries += `\n${pillarName}${pillarHasSignal ? ' [SIGNAL PRESENT — do NOT describe as zero evidence]' : ''}:\n`;
        let pillarItems = 0;
        for (const critId of criteriaIds) {
            const crit      = evaluationData[critId];
            const level     = (crit && crit.level) || 1;
            const itemCount = (crit && Array.isArray(crit.items)) ? crit.items.length : 0;
            // If this pillar has a signal but rubric level is 1, show it as baseline Initial
            // so the AI understands "signal detected but depth unconfirmed" not "absent"
            const effectiveLevel = (pillarHasSignal && level === 1) ? '1→2 (signal detected, rubric depth unconfirmed)' : `${level} (${LEVEL_LABELS[level] || 'Unknown'})`;
            pillarSummaries += `  - ${critId}: level=${effectiveLevel}, evidence_items_found=${itemCount}\n`;
            pillarItems += itemCount;
            totalItems  += itemCount;
        }
        if (pillarItems > 0 || pillarHasSignal) pillarsWithEvidence++;
    }

    const evidencedPillarList = signalEvidencedPillars.size > 0
        ? Array.from(signalEvidencedPillars).join(', ')
        : 'none confirmed by signals';

    const signalCtx = signalProfile
        ? `High-specificity governance evidence items: ${signalProfile.high_signals}
Medium-specificity governance evidence items: ${signalProfile.medium_signals}
Enterprise governance documentation items: ${signalProfile.enterprise_signals || 0}
Low-specificity items: ${signalProfile.low_signals}
Evidence quality description: ${frame ? frame.evidence_language : 'Limited publicly available governance documentation'}
Pillars with available evidence: ${evidencedPillarList}
Sample evidence matches: ${signalProfile.matched_phrases.slice(0,10).map(m=>`"${m.phrase}"[${m.tier}]`).join(', ') || 'none'}`
        : 'Evidence profile unavailable.';

    // Build interpretation constraints for the AI
    const partialNote = isPartial ? `
PARTIAL EVALUATION NOTE (MANDATORY):
- This evaluation is based on limited scraping data. The website blocked most content retrieval.
- Signals were detected from URL structure only — body content could not be confirmed.
- The confidence_explanation MUST acknowledge that evidence was partially obtained.
- Do NOT describe this as a complete assessment. Acknowledge data limitations clearly.
- Use language like: "Based on available signals, further documentation would strengthen this assessment."
` : '';

    const interpretationSection = frame ? `
INTERPRETATION FRAME (MANDATORY — follow exactly):
- Evidence language to use: "${frame.evidence_language}"
- Pillar baseline statement: "${frame.pillar_baseline}"
- Executive summary frame: "${frame.executive_frame}"
- FORBIDDEN phrases (do NOT use any of these): ${frame.forbidden_phrases.map(p => `"${p}"`).join(', ')}
- Pillars with available evidence MUST receive status_label of "Developing" or better.
- The executive_summary MUST describe what the evidence supports — NOT how many signals were found.
- The evidence_summary.summary MUST use evidence-based language (e.g. "publicly available evidence supports...") — NOT "signals identified".
- Do NOT use the word "signals" in executive_summary, confidence_explanation, or certification_statement.
${partialNote}` : `
INTERPRETATION FRAME:
- Limited publicly available governance documentation was found. Use "Limited publicly available governance documentation" in evidence_summary.
- Do not claim complete absence of governance — state that public documentation is limited.
${partialNote}`;

    const textPreview = scrapedText
        ? scrapedText.slice(0, 8000) + (scrapedText.length > 8000 ? '\n... [PREVIEW TRUNCATED]' : '')
        : '[No scraped text available]';

    return `Below is the HAI evaluation result for a company. Use it to generate the premium report.

DO NOT invent score numbers. DO NOT fill in snapshot fields — leave them null.
FOLLOW the interpretation frame exactly. It overrides raw rubric levels for narrative language.

-------------------------------------
CRITERION RESULTS BY PILLAR
-------------------------------------
${pillarSummaries}
SUMMARY: ${totalItems} total evidence items found across ${pillarsWithEvidence} of 6 pillars.
NOTE: Pillars marked [SIGNAL PRESENT] have governance evidence from URL signals even if rubric item count is 0.

-------------------------------------
GOVERNANCE SIGNAL PROFILE
-------------------------------------
${signalCtx}
${interpretationSection}
-------------------------------------
SCRAPED GOVERNANCE TEXT (PREVIEW)
-------------------------------------
${textPreview}

-------------------------------------
Now generate the structured HAI Premium Evaluation Report.
Return ONLY the JSON object. No markdown. No explanation.`;
}


// ---------------------------------------------------------------
// generatePremiumReport \u2014 main export
// ---------------------------------------------------------------
async function generatePremiumReport(evaluationData, scrapedText, scrapeContext) {

    if (!evaluationData || typeof evaluationData !== 'object') {
        console.warn('[report-generator] No evaluationData \u2014 skipping premium report');
        return null;
    }

    // Step 1: Signal detection
    const ctx            = scrapeContext || {};
    const isPartial      = !!(ctx.partialScrape || ctx.limitedAccess);
    const suppSignals    = ctx.supplementarySignals || null;

    // Detect signals from scraped text first
    const textSignals = detectGovernanceSignals(scrapedText);

    // Merge supplementary signals so blocked-scrape companies are not unfairly
    // penalised — EDGAR/OECD/GitHub signals count toward the evaluation gate.
    const suppHigh   = suppSignals ? (suppSignals.edgarSignals || 0) : 0;
    const suppMedium = suppSignals ? ((suppSignals.oecdSignals || 0) + (suppSignals.academicSignals || 0)) : 0;
    const suppLow    = suppSignals ? ((suppSignals.githubSignals || 0) + (suppSignals.waybackSignals || 0)) : 0;

    const signals = {
        high_signals:       textSignals.high_signals   + suppHigh,
        medium_signals:     textSignals.medium_signals + suppMedium,
        low_signals:        textSignals.low_signals    + suppLow,
        enterprise_signals: textSignals.enterprise_signals || 0,
        matched_phrases:    textSignals.matched_phrases
    };

    const evalState = determineEvaluationState(signals, isPartial);

    console.log(`[report-generator] Signals — high:${signals.high_signals} (text:${textSignals.high_signals}+supp:${suppHigh}) medium:${signals.medium_signals} enterprise:${signals.enterprise_signals||0} low:${signals.low_signals} state:${evalState} partial:${isPartial}`);

    // Step 2: Insufficient evidence gate — only fires when no signals at all,
    // even after fallback URL stubs are included in scrapedText.
    if (evalState === 'insufficient_evidence') {
        console.log('[report-generator] insufficient_evidence — returning structured refusal');
        return buildInsufficientEvidenceResponse(signals);
    }

    // Step 3: Tier and calibration
    // confPercent not available at backend — pass null so Tier3.5 downgrade
    // fires conservatively. Frontend re-applies with exact confPercent.
    const { tier, pillarsWithEvidence, downgraded } = classifySignalTier(signals, evaluationData, null);
    const rawScoreProxy = deriveRawScoreProxy(evaluationData);
    // confPercent not available here; frontend applies its own exact confPercent
    const scrapeBlocked = (ctx.scrapeStatus === "blocked") || (ctx.limitedAccess && !scrapedText);
    const calibration   = computeCalibration(rawScoreProxy, tier, pillarsWithEvidence, null, downgraded, signals, scrapeBlocked);
    console.log(`[report-generator] Tier:${tier} rawProxy:${rawScoreProxy} calibratedProxy:${calibration.calibrated_score} uplift:${calibration.uplift_applied} partial:${isPartial}`);

    // Step 4: Generate narrative report
    const userPrompt = buildUserPrompt(evaluationData, scrapedText, signals, isPartial);

    let response;
    try {
        response = await axios.post(OPENAI_API_URL, {
            model:           OPENAI_MODEL,
            temperature:     OPENAI_TEMP,
            response_format: { type: 'json_object' },
            messages: [
                { role: 'system', content: SYSTEM_PROMPT },
                { role: 'user',   content: userPrompt    }
            ]
        }, {
            timeout: OPENAI_TIMEOUT_MS,
            headers: { 'Authorization': 'Bearer ' + process.env.OPENAI_API_KEY, 'Content-Type': 'application/json' },
            validateStatus: () => true
        });
    } catch (err) {
        console.warn('[report-generator] OpenAI request failed:', err.message);
        return null;
    }

    if (response.status !== 200) {
        console.warn(`[report-generator] OpenAI returned HTTP ${response.status}`);
        return null;
    }

    const aiData  = response.data;
    const content = aiData?.choices?.[0]?.message?.content;
    if (!content) { console.warn('[report-generator] Empty content in OpenAI response'); return null; }

    let raw = content.trim();
    if (raw.startsWith('```json')) raw = raw.slice(7);
    if (raw.startsWith('```'))     raw = raw.slice(3);
    if (raw.endsWith('```'))       raw = raw.slice(0, -3);
    raw = raw.trim();

    let report;
    try { report = JSON.parse(raw); }
    catch (_) { console.warn('[report-generator] Failed to parse JSON from OpenAI response'); return null; }

    // Enforce snapshot nulls \u2014 frontend owns these
    if (report && report.snapshot) {
        report.snapshot.alignment_level = report.snapshot.evidence_strength =
        report.snapshot.certification_status = report.snapshot.benchmark_position = null;
    }

    // Step 5: Attach evaluation metadata
    report.evaluation_state = (evalState === 'partial_evaluation') ? 'partial_evaluation' : 'valid';
    report.signal_profile   = {
        high_signals: signals.high_signals, medium_signals: signals.medium_signals,
        low_signals: signals.low_signals, tier,
        matched_phrases: signals.matched_phrases.slice(0, 10)
    };
    report.calibration = {
        tier,
        uplift_applied:         calibration.uplift_applied,
        multi_pillar_bonus:     calibration.multi_pillar_bonus,
        raw_score_proxy:        rawScoreProxy,
        score_cap:              SCORE_CAP,
        evidence_cap_threshold: EVIDENCE_CAP_THRESHOLD,
        evidence_cap_value:     EVIDENCE_CAP_VALUE,
        downgraded:             calibration.downgraded,
        partial_evaluation:     isPartial
    };

    return report;
}


module.exports = { generatePremiumReport };
