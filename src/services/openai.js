'use strict';

// src/services/openai.js
// OpenAI GPT-4o evaluation engine
// Phase 6: adds executionLevel per criterion via OPENAI_EXECUTION_INSTRUCTION

const axios = require('axios');
const { OPENAI_EXECUTION_INSTRUCTION } = require('./proof-of-execution');

// ── Rubric criteria reference ───────────────────────────────────────────────
// Mirrors the rubric in bundle.js. Used to build the evaluation prompt.
// All 20 criteria across 6 pillars.
const RUBRIC_CRITERIA = [
    // Trust
    { id: 'trust_user_confidence',         label: 'User Confidence',           pillar: 'Trust' },
    { id: 'trust_consistency_of_behavior', label: 'Consistency of Behavior',   pillar: 'Trust' },
    { id: 'trust_ethical_intent',          label: 'Ethical Intent',            pillar: 'Trust' },
    { id: 'trust_absence_of_manipulation', label: 'Absence of Manipulation',   pillar: 'Trust' },
    // Accountability
    { id: 'accountability_ownership_of_outcomes',    label: 'Ownership of Outcomes',           pillar: 'Accountability' },
    { id: 'accountability_corrective_action',        label: 'Corrective Action',               pillar: 'Accountability' },
    { id: 'accountability_governance_and_oversight', label: 'Governance and Oversight',        pillar: 'Accountability' },
    // Purpose
    { id: 'purpose_mission_clarity',         label: 'Mission Clarity',           pillar: 'Purpose' },
    { id: 'purpose_human_centered_intent',   label: 'Human-Centered Intent',     pillar: 'Purpose' },
    { id: 'purpose_alignment_words_actions', label: 'Alignment: Words & Actions', pillar: 'Purpose' },
    // Safety
    { id: 'safety_risk_mitigation',              label: 'Risk Mitigation',              pillar: 'Safety' },
    { id: 'safety_user_protection_mechanisms',   label: 'User Protection Mechanisms',   pillar: 'Safety' },
    { id: 'safety_long_term_societal_safety',    label: 'Long-Term Societal Safety',    pillar: 'Safety' },
    // Transparency
    { id: 'transparency_explainability',         label: 'Explainability',           pillar: 'Transparency' },
    { id: 'transparency_data_disclosure',        label: 'Data Disclosure',          pillar: 'Transparency' },
    { id: 'transparency_communication_honesty',  label: 'Communication Honesty',    pillar: 'Transparency' },
    // Impact
    { id: 'impact_positive_human_outcomes',  label: 'Positive Human Outcomes',  pillar: 'Impact' },
    { id: 'impact_shared_human_benefit',     label: 'Shared Human Benefit',     pillar: 'Impact' },
    { id: 'impact_measurability_of_impact',  label: 'Measurability of Impact',  pillar: 'Impact' },
    { id: 'impact_durability_of_impact',     label: 'Durability of Impact',     pillar: 'Impact' },
];

// ── Evidence item IDs per criterion ────────────────────────────────────────
// Used in the prompt to tell GPT-4o which evidence IDs are checkable.
// Mirrors the rubric evidence structure in bundle.js.
const CRITERION_EVIDENCE_IDS = {
    trust_user_confidence:                  ['T1_R1','T1_R2','T1_R3','T1_S1','T1_S2','T1_S3','T1_G1','T1_G2'],
    trust_consistency_of_behavior:          ['T2_R1','T2_R2','T2_R3','T2_S1','T2_S2','T2_S3','T2_G1'],
    trust_ethical_intent:                   ['T3_R1','T3_R2','T3_R3','T3_S1','T3_S2','T3_S3','T3_G1','T3_G2'],
    trust_absence_of_manipulation:          ['T4_R1','T4_R2','T4_R3','T4_S1','T4_S2','T4_G1'],
    accountability_ownership_of_outcomes:   ['A1_R1','A1_R2','A1_R3','A1_S1','A1_S2','A1_S3','A1_G1'],
    accountability_corrective_action:       ['A2_R1','A2_R2','A2_R3','A2_S1','A2_S2','A2_G1'],
    accountability_governance_and_oversight:['A3_R1','A3_R2','A3_R3','A3_S1','A3_S2','A3_S3','A3_G1'],
    purpose_mission_clarity:                ['P1_R1','P1_R2','P1_R3','P1_S1','P1_S2','P1_G1','P1_G2'],
    purpose_human_centered_intent:          ['P2_R1','P2_R2','P2_R3','P2_S1','P2_S2','P2_G1'],
    purpose_alignment_words_actions:        ['P3_R1','P3_R2','P3_R3','P3_S1','P3_S2','P3_G1'],
    safety_risk_mitigation:                 ['S1_R1','S1_R2','S1_R3','S1_S1','S1_S2','S1_S3','S1_G1'],
    safety_user_protection_mechanisms:      ['S2_R1','S2_R2','S2_R3','S2_S1','S2_S2','S2_G1'],
    safety_long_term_societal_safety:       ['S3_R1','S3_R2','S3_R3','S3_S1','S3_S2','S3_G1'],
    transparency_explainability:            ['TR1_R1','TR1_R2','TR1_R3','TR1_S1','TR1_S2','TR1_G1'],
    transparency_data_disclosure:           ['TR2_R1','TR2_R2','TR2_R3','TR2_S1','TR2_S2','TR2_S3','TR2_G1'],
    transparency_communication_honesty:     ['TR3_R1','TR3_R2','TR3_R3','TR3_S1','TR3_S2','TR3_G1'],
    impact_positive_human_outcomes:         ['I1_R1','I1_R2','I1_R3','I1_S1','I1_S2','I1_S3','I1_G1'],
    impact_shared_human_benefit:            ['I2_R1','I2_R2','I2_R3','I2_S1','I2_S2','I2_G1'],
    impact_measurability_of_impact:         ['I3_R1','I3_R2','I3_R3','I3_S1','I3_S2','I3_G1'],
    impact_durability_of_impact:            ['I4_R1','I4_R2','I4_R3','I4_S1','I4_G1'],
};

// ── Build system prompt ─────────────────────────────────────────────────────
function buildSystemPrompt() {
    const criteriaList = RUBRIC_CRITERIA.map(c =>
        `  - ${c.id} (${c.pillar}: ${c.label})`
    ).join('\n');

    return `You are the HAI (Human Alignment Index) evaluation engine for Humaital.
You assess organisations against a 20-criterion governance rubric across six pillars:
Trust, Accountability, Purpose, Safety, Transparency, and Impact.

Your task: analyse the provided governance text and return a structured JSON evaluation
object assigning a maturity level (1–5) and checked evidence item IDs for each criterion.

MATURITY LEVELS:
  1 = No evidence found
  2 = Basic intent or policy reference found
  3 = Structured documentation or partial implementation found
  4 = Comprehensive governance practice with evidence found
  5 = Externally verified, measurable, and sustained practice found

CRITERIA TO EVALUATE:
${criteriaList}

${OPENAI_EXECUTION_INSTRUCTION}

OUTPUT FORMAT:
Return a single valid JSON object only. No prose, no markdown, no preamble.
Each criterion must be a key in the object with this exact structure:
{
  "criterion_id": {
    "level": <integer 1-5>,
    "items": [<array of matching evidence item IDs from the provided list>],
    "executionLevel": "<verified|partial|asserted|none>",
    "reasoning": "<1-2 sentence explanation of why this level was assigned>"
  }
}

IMPORTANT RULES:
- Assign level 1 when no relevant evidence is found. Do not inflate levels.
- Items must only include IDs from the provided evidence ID list for each criterion.
- executionLevel must be set for every criterion — no exceptions.
- reasoning must be concise and evidence-specific, not generic.
- If the text has no governance content at all, assign level 1 and executionLevel "none" to all criteria.
- Base your evaluation strictly on the text provided. Do not use external knowledge.

Respond with a valid JSON object only. No other text.`.trim();
}

// ── Build user message ──────────────────────────────────────────────────────
function buildUserMessage(combinedText, companyName, industry) {
    const textLen = combinedText ? combinedText.trim().length : 0;
    const isThinContent = textLen > 0 && textLen < 1000;
    const isNoContent   = textLen === 0;

    let textSection;
    if (isNoContent) {
        textSection = `No governance text was retrieved for ${companyName} (${industry}). Assign level 1 and executionLevel "none" to all criteria.`;
    } else if (isThinContent) {
        textSection = `WARNING: Only ${textLen} characters of text were retrieved for ${companyName} (${industry}). This is likely cookie notices, redirect pages, or access-blocked content with no governance information.

MANDATORY INSTRUCTION: Because the text is too short to contain real governance evidence, you MUST assign level 1 and executionLevel "none" to ALL criteria without exception. Do not assign any level above 1.

TEXT (for reference only — treat as insufficient evidence):
${combinedText.trim()}`;
    } else {
        textSection = `GOVERNANCE TEXT FROM ${companyName.toUpperCase()} (${industry}):\n\n${combinedText.slice(0, 14000)}`;
    }

    const evidenceIdsSection = RUBRIC_CRITERIA.map(c => {
        const ids = CRITERION_EVIDENCE_IDS[c.id] || [];
        return `${c.id}: [${ids.join(', ')}]`;
    }).join('\n');

    return `${textSection}

AVAILABLE EVIDENCE ITEM IDs PER CRITERION (only use IDs from this list in your response):
${evidenceIdsSection}

Evaluate the governance text above against all 20 criteria and return the JSON object.`;
}

// ── callOpenAI — main export ────────────────────────────────────────────────
async function callOpenAI(combinedText, companyName, industry) {
    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) throw new Error('OPENAI_API_KEY is not set');

    const systemPrompt = buildSystemPrompt();
    const userMessage  = buildUserMessage(combinedText, companyName || 'Unknown', industry || 'Technology');

    const requestBody = {
        model:           'gpt-4o',
        max_tokens:      4000,
        temperature:     0.1,   // low temperature for consistent structured output
        response_format: { type: 'json_object' },
        messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user',   content: userMessage  },
        ],
    };

    let attempt = 0;
    const maxAttempts = 2;
    let lastError;

    while (attempt < maxAttempts) {
        attempt++;
        try {
            const response = await axios.post(
                'https://api.openai.com/v1/chat/completions',
                requestBody,
                {
                    headers: {
                        'Content-Type':  'application/json',
                        'Authorization': `Bearer ${apiKey}`,
                    },
                    timeout: 90000,  // 90s — GPT-4o can be slow on large contexts
                }
            );

            const content = response.data?.choices?.[0]?.message?.content;
            if (!content) throw new Error('Empty response from OpenAI');

            // Parse and validate
            let parsed;
            try {
                parsed = JSON.parse(content);
            } catch (parseErr) {
                // Attempt to strip any accidental markdown fences
                const cleaned = content.replace(/```json|```/g, '').trim();
                parsed = JSON.parse(cleaned);
            }

            // Validate: must have at least some criterion keys
            const validKeys = Object.keys(parsed).filter(k =>
                RUBRIC_CRITERIA.some(c => c.id === k)
            );
            if (validKeys.length === 0) {
                throw new Error('OpenAI response contains no recognisable criterion IDs');
            }

            // Normalise: ensure every criterion is present with defaults if missing
            // Hard enforcement: thin/no content cannot produce levels above 1 regardless
            // of what GPT-4o returns — this prevents default L2 inflation.
            const _forceLevelOne = isNoContent || isThinContent;
            const normalised = {};
            RUBRIC_CRITERIA.forEach(c => {
                const raw = parsed[c.id] || {};
                const rawLevel = Math.max(1, Math.min(5, parseInt(raw.level, 10) || 1));
                normalised[c.id] = {
                    level:          _forceLevelOne ? 1 : rawLevel,
                    items:          _forceLevelOne ? [] : (Array.isArray(raw.items) ? raw.items : []),
                    executionLevel: _forceLevelOne ? 'none' : (['verified','partial','asserted','none'].includes(raw.executionLevel) ? raw.executionLevel : 'none'),
                    reasoning:      typeof raw.reasoning === 'string' ? raw.reasoning.slice(0, 200) : '',
                };
            });
            if (_forceLevelOne) {
                console.log(`[HAI] Forced all criteria to L1 — content too thin (${textLen} chars) to support any level above 1.`);
            }

            console.log(`[HAI] OpenAI attempt ${attempt} succeeded. Valid criteria: ${validKeys.length}/20`);
            return normalised;

        } catch (err) {
            lastError = err;
            const isRetryable = err.response?.status === 429 || err.response?.status >= 500 || err.code === 'ECONNABORTED';
            console.warn(`[HAI] OpenAI attempt ${attempt} failed: ${err.message}` + (isRetryable && attempt < maxAttempts ? ' — retrying...' : ''));
            if (!isRetryable || attempt >= maxAttempts) break;
            await new Promise(r => setTimeout(r, 3000 * attempt));
        }
    }

    throw new Error(`OpenAI evaluation failed after ${maxAttempts} attempts: ${lastError?.message}`);
}

module.exports = { callOpenAI, RUBRIC_CRITERIA, CRITERION_EVIDENCE_IDS };
