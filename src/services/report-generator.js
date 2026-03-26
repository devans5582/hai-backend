'use strict';

const axios = require('axios');

// ---------------------------------------------------------------
// Configuration — same model as /evaluate but separate timeout.
// The premium report prompt is longer and produces more output,
// so 60s is safer than the 45s used for the evaluation call.
// ---------------------------------------------------------------
const OPENAI_API_URL    = 'https://api.openai.com/v1/chat/completions';
const OPENAI_MODEL      = 'gpt-4o';
const OPENAI_TEMP       = 0.3;
const OPENAI_TIMEOUT_MS = 60000;

// ---------------------------------------------------------------
// System prompt — verbatim from the approved Phase 3 specification.
//
// IMPORTANT: snapshot fields (alignment_level, evidence_strength,
// certification_status, benchmark_position) are returned as null.
// They are populated by the frontend after exact client-side score
// calculations complete. This prevents any conflict between backend
// estimates and the authoritative frontend-computed values.
// ---------------------------------------------------------------
const SYSTEM_PROMPT = `You are generating a Humaital Human-Alignment Index (HAI) Premium Evaluation Report.

This output will be used in a web UI and a formal PDF report. It must be clear, structured, concise, and actionable.

You are NOT writing a narrative article.
You ARE generating a structured evaluation report.

-------------------------------------
CRITICAL RULES (DO NOT VIOLATE)
-------------------------------------

- Use plain English (5th–8th grade reading level)
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
- 2–3 sentences
- Describe overall alignment direction and evidence quality based on what was found
- Do NOT reference a score number — the snapshot will carry score context

SCORE INTERPRETATION:
- Max 4 sentences
- Explain what the HAI Score and Evidence Strength mean in plain language
- Do NOT invent score numbers

SNAPSHOT:
- All four fields must be null — do not fill them in

PILLARS:
- Exactly 6 pillars in this order: Trust, Accountability, Purpose, Safety, Transparency, Impact
- Each must include:
  - status_label: one of: Strong | Progressing | Developing | Needs Attention
  - what_we_found: 1–2 short sentences based on the criterion levels and evidence provided
  - why_it_matters: 1 sentence
  - next_step: 1 sentence starting with an action verb

STRENGTHS:
- 2–3 items minimum
- Must be grounded in the evidence data provided

IMPROVEMENT AREAS:
- 3–5 items
- Each must include what_we_found, why_it_matters, what_to_do_next
- what_to_do_next must start with an action verb
- No sentence over 20 words

ACTION PLAN:
- immediate_actions: 0–30 days
- near_term_improvements: 30–90 days
- long_term_strengthening: 90+ days
- Each item is a plain string — clear and practical

CONFIDENCE EXPLANATION:
- 3–4 sentences
- Must explain that confidence reflects evidence visibility, not internal practice quality

EVIDENCE SUMMARY:
- core_governance: one of: Strong | Emerging | Limited | None
- operational_evidence: one of: Strong | Emerging | Limited | None
- external_validation: one of: Strong | Limited | None
- summary: 1 short sentence

CERTIFICATION STATEMENT:
- 2–3 sentences
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
// buildUserPrompt
//
// Converts evaluationData (the 20-criterion rubric result from
// callOpenAI) and the scraped text into a structured input block
// for the Phase 3 prompt.
//
// Does NOT compute scores, confidence percentages, or certification
// status — those remain the exclusive domain of the frontend.
// ---------------------------------------------------------------
function buildUserPrompt(evaluationData, scrapedText) {

    // Pillar groupings — matches rubric.js pillar structure exactly
    const PILLAR_CRITERIA = {
        Trust: [
            'trust_user_confidence',
            'trust_consistency_of_behavior',
            'trust_ethical_intent',
            'trust_absence_of_manipulation'
        ],
        Accountability: [
            'accountability_ownership_of_outcomes',
            'accountability_corrective_action',
            'accountability_governance_and_oversight'
        ],
        Purpose: [
            'purpose_mission_clarity',
            'purpose_human_centered_intent',
            'purpose_alignment_words_actions'
        ],
        Safety: [
            'safety_risk_mitigation',
            'safety_user_protection_mechanisms',
            'safety_long_term_societal_safety'
        ],
        Transparency: [
            'transparency_explainability',
            'transparency_data_disclosure',
            'transparency_communication_honesty'
        ],
        Impact: [
            'impact_positive_human_outcomes',
            'impact_shared_human_benefit',
            'impact_measurability_of_impact',
            'impact_durability_of_impact'
        ]
    };

    // Build a plain-language pillar summary from criterion levels and item counts.
    // No math — just readable labels the AI can reason from.
    const LEVEL_LABELS = {
        1: 'Not Present',
        2: 'Initial',
        3: 'Developing',
        4: 'Established',
        5: 'Advanced'
    };

    let pillarSummaries = '';
    for (const [pillarName, criteriaIds] of Object.entries(PILLAR_CRITERIA)) {
        pillarSummaries += `\n${pillarName}:\n`;
        for (const critId of criteriaIds) {
            const crit = evaluationData[critId];
            if (!crit) {
                pillarSummaries += `  - ${critId}: level=Not Present, evidence_items=0\n`;
                continue;
            }
            const level      = crit.level || 1;
            const itemCount  = Array.isArray(crit.items) ? crit.items.length : 0;
            const levelLabel = LEVEL_LABELS[level] || 'Unknown';
            pillarSummaries += `  - ${critId}: level=${level} (${levelLabel}), evidence_items_found=${itemCount}\n`;
        }
    }

    // Count evidence items by pillar for the evidence_summary section.
    // This gives the AI grounding for core/operational/external labels
    // without the AI needing to do score math.
    let totalItems = 0;
    let pillarsWithEvidence = 0;
    for (const [, criteriaIds] of Object.entries(PILLAR_CRITERIA)) {
        let pillarItems = 0;
        for (const critId of criteriaIds) {
            const crit = evaluationData[critId];
            if (crit && Array.isArray(crit.items)) {
                pillarItems += crit.items.length;
                totalItems  += crit.items.length;
            }
        }
        if (pillarItems > 0) pillarsWithEvidence++;
    }

    // Scraped text preview — enough for context without exceeding token budget.
    // The evaluation call already used the full text; here we send 8,000 chars
    // to give the report generator evidence context for the narrative sections.
    const textPreview = scrapedText
        ? scrapedText.slice(0, 8000) + (scrapedText.length > 8000 ? '\n... [PREVIEW TRUNCATED]' : '')
        : '[No scraped text available]';

    return `Below is the HAI evaluation result for a company. Use it to generate the premium report.

DO NOT invent score numbers. DO NOT fill in snapshot fields — leave them null.
Base your narrative on the criterion levels and evidence patterns shown below.

-------------------------------------
CRITERION RESULTS BY PILLAR
-------------------------------------
${pillarSummaries}
SUMMARY: ${totalItems} total evidence items found across ${pillarsWithEvidence} of 6 pillars.

-------------------------------------
SCRAPED GOVERNANCE TEXT (PREVIEW)
-------------------------------------
${textPreview}

-------------------------------------
Now generate the structured HAI Premium Evaluation Report.
Return ONLY the JSON object. No markdown. No explanation.`;
}


// ---------------------------------------------------------------
// generatePremiumReport
//
// Main export. Called from evaluate.js after evaluationData is
// populated. Returns the structured report object or null on any
// failure — never throws.
//
// @param {Object} evaluationData  - 20-criterion result from callOpenAI
// @param {string} scrapedText     - combined_text from scrapeCompanyPages
// @returns {Promise<Object|null>}
// ---------------------------------------------------------------
async function generatePremiumReport(evaluationData, scrapedText) {

    if (!evaluationData || typeof evaluationData !== 'object') {
        console.warn('[report-generator] No evaluationData — skipping premium report');
        return null;
    }

    const userPrompt = buildUserPrompt(evaluationData, scrapedText);

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
            headers: {
                'Authorization': 'Bearer ' + process.env.OPENAI_API_KEY,
                'Content-Type':  'application/json'
            },
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

    const aiData = response.data;
    const content = aiData &&
                    aiData.choices &&
                    aiData.choices[0] &&
                    aiData.choices[0].message &&
                    aiData.choices[0].message.content;

    if (!content) {
        console.warn('[report-generator] Empty content in OpenAI response');
        return null;
    }

    // Strip markdown fences if present (defensive — json_object mode should prevent this)
    let raw = content.trim();
    if (raw.startsWith('```json')) raw = raw.slice(7);
    if (raw.startsWith('```'))     raw = raw.slice(3);
    if (raw.endsWith('```'))       raw = raw.slice(0, -3);
    raw = raw.trim();

    let report;
    try {
        report = JSON.parse(raw);
    } catch (_) {
        console.warn('[report-generator] Failed to parse JSON from OpenAI response');
        return null;
    }

    // Enforce that snapshot fields are null — the frontend owns these values.
    // If the AI filled them in despite instructions, reset them here.
    if (report && report.snapshot) {
        report.snapshot.alignment_level      = null;
        report.snapshot.evidence_strength    = null;
        report.snapshot.certification_status = null;
        report.snapshot.benchmark_position   = null;
    }

    return report;
}


module.exports = { generatePremiumReport };
