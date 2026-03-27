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
- Ensure language is simple and clear`;


// ---------------------------------------------------------------
// GOVERNANCE SIGNAL DETECTION
// ---------------------------------------------------------------

const HIGH_SIGNAL_PATTERNS = [
    /responsible\s+ai/i,
    /ai\s+principles/i,
    /ai\s+governance/i,
    /governance\s+framework/i,
    /ai\s+ethics/i,
    /ethical\s+ai/i,
    /ai\s+safety/i,
    /safety\s+framework/i,
    /ai\s+policy\s+hub/i,
    /dedicated\s+ai\s+policy/i,
    /human.{0,10}alignment/i,
    /trustworthy\s+ai/i,
    /responsible\s+technology/i,
    /ai\s+accountability/i,
];

const MEDIUM_SIGNAL_PATTERNS = [
    /trust\s+cent(?:er|re)/i,
    /transparency\s+report/i,
    /transparency\s+disclosure/i,
    /public\s+commitment/i,
    /governance\s+disclosure/i,
    /structured\s+governance/i,
    /data\s+governance/i,
    /algorithmic\s+accountability/i,
    /ai\s+use\s+policy/i,
    /model\s+card/i,
    /system\s+card/i,
    /impact\s+assessment/i,
    /risk\s+management\s+framework/i,
];

const LOW_SIGNAL_PATTERNS = [
    /privacy\s+policy/i,
    /terms\s+of\s+(use|service)/i,
    /cookie\s+policy/i,
    /legal\s+notice/i,
    /disclaimer/i,
    /copyright\s+notice/i,
    /marketing/i,
];

function detectGovernanceSignals(scrapedText) {
    if (!scrapedText || typeof scrapedText !== 'string') {
        return { high_signals: 0, medium_signals: 0, low_signals: 0, matched_phrases: [] };
    }
    const matched = [];
    let high = 0, medium = 0, low = 0;
    for (const p of HIGH_SIGNAL_PATTERNS) {
        if (p.test(scrapedText)) { high++; const m = scrapedText.match(p); if (m) matched.push({ tier: 'high', phrase: m[0].trim() }); }
    }
    for (const p of MEDIUM_SIGNAL_PATTERNS) {
        if (p.test(scrapedText)) { medium++; const m = scrapedText.match(p); if (m) matched.push({ tier: 'medium', phrase: m[0].trim() }); }
    }
    for (const p of LOW_SIGNAL_PATTERNS) {
        if (p.test(scrapedText)) { low++; const m = scrapedText.match(p); if (m) matched.push({ tier: 'low', phrase: m[0].trim() }); }
    }
    return { high_signals: high, medium_signals: medium, low_signals: low, matched_phrases: matched };
}


// ---------------------------------------------------------------
// EVALUATION STATE
// ---------------------------------------------------------------
function determineEvaluationState(signals) {
    if (signals.high_signals === 0 && signals.medium_signals === 0) {
        return 'insufficient_evidence';
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
        reason: 'Limited visible governance signals detected. The assessment cannot produce a verified HAI Score without meaningful evidence of AI governance practices.',
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

function classifySignalTier(signals, evaluationData) {
    const { high_signals, medium_signals } = signals;
    const pillarsWithEvidence = countPillarsWithEvidence(evaluationData);
    if (high_signals >= 4 && pillarsWithEvidence >= 4) return { tier: 4, pillarsWithEvidence };
    if (high_signals >= 3)                             return { tier: 3, pillarsWithEvidence };
    if (high_signals >= 1)                             return { tier: 2, pillarsWithEvidence };
    if (medium_signals >= 1)                           return { tier: 1, pillarsWithEvidence };
    return { tier: 0, pillarsWithEvidence };
}


// ---------------------------------------------------------------
// CALIBRATION (BOUNDED UPLIFT)
// ---------------------------------------------------------------

const UPLIFT_MIDPOINTS = { 1: 4, 2: 11, 3: 24, 4: 35 };
const SCORE_CAP = 85;

function computeCalibration(rawScore, tier, pillarsWithEvidence, confPercent) {
    if (tier === 0) return { calibrated_score: rawScore, uplift_applied: 0, multi_pillar_bonus: 0, tier };
    let uplift = UPLIFT_MIDPOINTS[tier] || 0;
    // Confidence modifier: reduce uplift 20% when evidence strength < 50%
    if (typeof confPercent === 'number' && confPercent < 50) {
        uplift = Math.round(uplift * 0.8);
    }
    const multiPillarBonus = pillarsWithEvidence >= 4 ? 5 : 0;
    const finalScore = Math.min(Math.max(rawScore + uplift + multiPillarBonus, 1), SCORE_CAP);
    return { calibrated_score: Math.round(finalScore * 10) / 10, uplift_applied: uplift, multi_pillar_bonus: multiPillarBonus, tier };
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
function buildUserPrompt(evaluationData, scrapedText, signalProfile) {
    const LEVEL_LABELS = { 1: 'Not Present', 2: 'Initial', 3: 'Developing', 4: 'Established', 5: 'Advanced' };
    let pillarSummaries = '';
    let totalItems = 0, pillarsWithEvidence = 0;

    for (const [pillarName, criteriaIds] of Object.entries(_PILLAR_CRITERIA)) {
        pillarSummaries += `\n${pillarName}:\n`;
        let pillarItems = 0;
        for (const critId of criteriaIds) {
            const crit      = evaluationData[critId];
            const level     = (crit && crit.level) || 1;
            const itemCount = (crit && Array.isArray(crit.items)) ? crit.items.length : 0;
            pillarSummaries += `  - ${critId}: level=${level} (${LEVEL_LABELS[level] || 'Unknown'}), evidence_items_found=${itemCount}\n`;
            pillarItems += itemCount;
            totalItems  += itemCount;
        }
        if (pillarItems > 0) pillarsWithEvidence++;
    }

    const signalCtx = signalProfile
        ? `High-value signals: ${signalProfile.high_signals}\nMedium-value signals: ${signalProfile.medium_signals}\nLow-value signals: ${signalProfile.low_signals}\nSample matches: ${signalProfile.matched_phrases.slice(0,6).map(m=>`"${m.phrase}"[${m.tier}]`).join(', ') || 'none'}`
        : 'Signal profile unavailable.';

    const textPreview = scrapedText
        ? scrapedText.slice(0, 8000) + (scrapedText.length > 8000 ? '\n... [PREVIEW TRUNCATED]' : '')
        : '[No scraped text available]';

    return `Below is the HAI evaluation result for a company. Use it to generate the premium report.

DO NOT invent score numbers. DO NOT fill in snapshot fields \u2014 leave them null.

-------------------------------------
CRITERION RESULTS BY PILLAR
-------------------------------------
${pillarSummaries}
SUMMARY: ${totalItems} total evidence items found across ${pillarsWithEvidence} of 6 pillars.

-------------------------------------
GOVERNANCE SIGNAL PROFILE
-------------------------------------
${signalCtx}

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
async function generatePremiumReport(evaluationData, scrapedText) {

    if (!evaluationData || typeof evaluationData !== 'object') {
        console.warn('[report-generator] No evaluationData \u2014 skipping premium report');
        return null;
    }

    // Step 1: Signal detection
    const signals   = detectGovernanceSignals(scrapedText);
    const evalState = determineEvaluationState(signals);
    console.log(`[report-generator] Signals \u2014 high:${signals.high_signals} medium:${signals.medium_signals} low:${signals.low_signals} state:${evalState}`);

    // Step 2: Insufficient evidence gate
    if (evalState === 'insufficient_evidence') {
        console.log('[report-generator] insufficient_evidence \u2014 returning structured refusal');
        return buildInsufficientEvidenceResponse(signals);
    }

    // Step 3: Tier and calibration
    const { tier, pillarsWithEvidence } = classifySignalTier(signals, evaluationData);
    const rawScoreProxy = deriveRawScoreProxy(evaluationData);
    // confPercent not available here; frontend applies its own exact confPercent
    const calibration   = computeCalibration(rawScoreProxy, tier, pillarsWithEvidence, null);
    console.log(`[report-generator] Tier:${tier} rawProxy:${rawScoreProxy} calibratedProxy:${calibration.calibrated_score} uplift:${calibration.uplift_applied}`);

    // Step 4: Generate narrative report
    const userPrompt = buildUserPrompt(evaluationData, scrapedText, signals);

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
    report.evaluation_state = 'valid';
    report.signal_profile   = {
        high_signals: signals.high_signals, medium_signals: signals.medium_signals,
        low_signals: signals.low_signals, tier,
        matched_phrases: signals.matched_phrases.slice(0, 10)
    };
    report.calibration = {
        tier, uplift_applied: calibration.uplift_applied,
        multi_pillar_bonus: calibration.multi_pillar_bonus,
        raw_score_proxy: rawScoreProxy, score_cap: SCORE_CAP
    };

    return report;
}


module.exports = { generatePremiumReport };
