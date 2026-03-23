'use strict';

const axios = require('axios');

// ---------------------------------------------------------------
// OpenAI configuration — matches WordPress snippet exactly
// ---------------------------------------------------------------
const OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions';
const OPENAI_MODEL   = 'gpt-4o';
const OPENAI_TEMP    = 0.2;
const OPENAI_TIMEOUT = 45000; // 45 seconds — matches WordPress snippet

// ---------------------------------------------------------------
// System prompt — verbatim from the WordPress snippet.
// All 141 item IDs and 20 criterion keys confirmed to match
// rubric.js exactly (cross-reference completed before Phase 1).
// ---------------------------------------------------------------
const SYSTEM_PROMPT = `You are an expert AI governance auditor. You evaluate companies based on the Humaital HAI (Human-Aligned AI) framework.

Analyze the provided scraped text from the company's website (including policies and terms of use) and determine their maturity level (2-5) for each pillar criterion.

Also, identify which specific required or strong evidence items are explicitly present in the text.

You MUST respond with ONLY a raw, valid JSON object mapping each criterion ID EXACTLY as listed to its assigned level (1-5), and an array of checked item IDs matching EXACTLY the specific IDs provided to you in the user prompt (e.g., "T1_R1", "S1_G1", etc) that the text satisfies. If no items are satisfied, return an empty array \`[]\`.

EXPECTED JSON TEMPLATE (The 'level' values below are just placeholders. You MUST replace them with your genuine assessed maturity level 2-5):
{
  "trust_user_confidence": { "level": 1, "items": [] },
  "trust_consistency_of_behavior": { "level": 1, "items": [] },
  "trust_ethical_intent": { "level": 1, "items": [] },
  "trust_absence_of_manipulation": { "level": 1, "items": [] },
  "accountability_ownership_of_outcomes": { "level": 1, "items": [] },
  "accountability_corrective_action": { "level": 1, "items": [] },
  "accountability_governance_and_oversight": { "level": 1, "items": [] },
  "purpose_mission_clarity": { "level": 1, "items": [] },
  "purpose_human_centered_intent": { "level": 1, "items": [] },
  "purpose_alignment_words_actions": { "level": 1, "items": [] },
  "safety_risk_mitigation": { "level": 1, "items": [] },
  "safety_user_protection_mechanisms": { "level": 1, "items": [] },
  "safety_long_term_societal_safety": { "level": 1, "items": [] },
  "transparency_explainability": { "level": 1, "items": [] },
  "transparency_data_disclosure": { "level": 1, "items": [] },
  "transparency_communication_honesty": { "level": 1, "items": [] },
  "impact_positive_human_outcomes": { "level": 1, "items": [] },
  "impact_shared_human_benefit": { "level": 1, "items": [] },
  "impact_measurability_of_impact": { "level": 1, "items": [] },
  "impact_durability_of_impact": { "level": 1, "items": [] }
}`;

// ---------------------------------------------------------------
// Rubric mappings — verbatim from the WordPress snippet.
// Provided in the user turn so OpenAI knows which item IDs are
// valid to return in each criterion's items array.
// ---------------------------------------------------------------
const RUBRIC_MAPPINGS = `
[trust_user_confidence] T1_R1: AI-related user support path, T1_R2: User-facing expectations, T1_R3: Feedback channel, T1_S1: Trust metrics, T1_S2: User testing evidence, T1_S3: Incident log category, T1_G1: Trust center page, T1_G2: Customer references

[trust_consistency_of_behavior] T2_R1: QA/testing plan, T2_R2: Release log, T2_R3: Monitoring plan, T2_S1: Regression results, T2_S2: Runbooks SLAs, T2_S3: Approval audit trail, T2_G1: Public status info

[trust_ethical_intent] T3_R1: Ethical principles/policy, T3_R2: Decision framework, T3_R3: Named accountable role, T3_S1: Ethics review cadence, T3_S2: Documented tradeoffs, T3_S3: Ethics in SDLC, T3_G1: Public AI principles

[trust_absence_of_manipulation] T4_R1: UX guidelines prohibiting dark patterns, T4_R2: Consent flows, T4_R3: Disclosure where persuasion used, T4_S1: Risk review checklist, T4_S2: A/B test governance, T4_S3: Evidence of feature changes, T4_G1: External assessments

[accountability_ownership_of_outcomes] A1_R1: Responsibility statement, A1_R2: Named owner scope, A1_R3: Escalation path, A1_S1: Redacted incident report, A1_S2: Vendor contracts, A1_S3: Public remediation commitment, A1_G1: Leadership comms

[accountability_corrective_action] A2_R1: Incident response playbook, A2_R2: Post-incident review, A2_R3: Action tracking, A2_S1: Proactive fixes, A2_S2: Preventative controls, A2_S3: Remediation metrics, A2_G1: Public postmortems

[accountability_governance_and_oversight] A3_R1: Governance structure charter, A3_R2: Decision rights, A3_R3: Periodic review, A3_S1: Independent oversight, A3_S2: Decision logs, A3_S3: Leadership dashboards, A3_G1: Advisory board/audits

[purpose_mission_clarity] P1_R1: Mission statement, P1_R2: System purpose statement, P1_R3: Communication evidence, P1_S1: Strategy tied to mission, P1_S2: OKRs mapped to mission, P1_S3: Prioritization decisions, P1_G1: Consistent messaging

[purpose_human_centered_intent] P2_R1: Requirements for human impact, P2_R2: Stakeholder identification, P2_R3: Harm/benefit assessment, P2_S1: Human-in-loop policy, P2_S2: Accessibility practices, P2_S3: Design research, P2_G1: Human-benefit stories

[purpose_alignment_words_actions] P3_R1: Actions match purpose, P3_R2: Addressing misalignment, P3_R3: Defined success beyond profit, P3_S1: Enforcement on drift, P3_S2: Mission-aligned behavior metrics, P3_S3: Reporting outcomes, P3_G1: 3rd party validation

[safety_risk_mitigation] S1_R1: Risk assessment template, S1_R2: Risk register, S1_R3: Pre-launch signoff, S1_S1: Red-teaming, S1_S2: Risk monitoring plan, S1_S3: Rollback procedures, S1_G1: Security posture docs

[safety_user_protection_mechanisms] S2_R1: Guardrails policy, S2_R2: Abuse reporting, S2_R3: Access controls, S2_S1: Real-time monitoring, S2_S2: Safety tuning process, S2_S3: User remediation, S2_G1: Public safety center

[safety_long_term_societal_safety] S3_R1: Long-term impact docs, S3_R2: Systemic risks, S3_R3: Mitigation plan, S3_S1: Scenario analysis, S3_S2: External engagement, S3_S3: Decision examples, S3_G1: Progress updates

[transparency_explainability] TR1_R1: Plain-language explanation, TR1_R2: Why-this-outcome mechanism, TR1_R3: Limitations listed, TR1_S1: Explanation standards, TR1_S2: Decision traceability, TR1_S3: Contest/appeal process, TR1_G1: System cards

[transparency_data_disclosure] TR2_R1: Privacy policy matches reality, TR2_R2: Data sharing info, TR2_R3: Retention/deletion policy, TR2_S1: User controls, TR2_S2: Data inventory, TR2_S3: Training data policy, TR2_G1: Data transparency reports

[transparency_communication_honesty] TR3_R1: Incident comms process, TR3_R2: Marketing accuracy standards, TR3_R3: Limitations disclosure policy, TR3_S1: Timely disclosure evidence, TR3_S2: Negative updates examples, TR3_S3: Proactive updates, TR3_G1: Changelog

[impact_positive_human_outcomes] I1_R1: Defined outcomes, I1_R2: Outcome metrics, I1_R3: Attribution rationale, I1_S1: Multi-metric evaluation, I1_S2: Independent eval, I1_S3: Consistent improvements, I1_G1: Measured case studies

[impact_shared_human_benefit] I2_R1: Communities impacted recorded, I2_R2: Equity considered, I2_R3: Mitigation plan for narrow benefits, I2_S1: Access policies, I2_S2: Distributional effects measured, I2_S3: Community engagement, I2_G1: Community partnerships

[impact_measurability_of_impact] I3_R1: Measurement method, I3_R2: Reporting cadence, I3_R3: Named owner, I3_S1: Repeatable methodology, I3_S2: Impact dashboard, I3_S3: Public reporting, I3_G1: External frameworks referenced

[impact_durability_of_impact] I4_R1: Longitudinal metrics, I4_R2: Sustainability plan, I4_R3: Risks to impact identified, I4_S1: Maintenance investment, I4_S2: Benefits enduring without intervention, I4_S3: Second-order effects monitored, I4_G1: Multi-year studies
`;


// ---------------------------------------------------------------
// Main export
// ---------------------------------------------------------------

/**
 * Calls the OpenAI API with scraped company text and returns the
 * structured 20-criterion evaluation object.
 *
 * @param {string} combinedText - Scraped and truncated governance text
 * @returns {Promise<Object>} 20-criterion evaluation object
 * @throws {Error} on API failure, timeout, or unparseable JSON
 */
async function callOpenAI(combinedText) {

    const userPrompt =
        'Here are the acceptable item IDs for each criterion you can return inside the `items` array:\n' +
        RUBRIC_MAPPINGS +
        '\n\nHere is the scraped governance text for the company:\n' +
        combinedText;

    const requestBody = {
        model:           OPENAI_MODEL,
        temperature:     OPENAI_TEMP,
        response_format: { type: 'json_object' },
        messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            { role: 'user',   content: userPrompt    }
        ]
    };

    let response;
    try {
        response = await axios.post(OPENAI_API_URL, requestBody, {
            timeout: OPENAI_TIMEOUT,
            headers: {
                'Authorization': 'Bearer ' + process.env.OPENAI_API_KEY,
                'Content-Type':  'application/json'
            },
            validateStatus: () => true
        });
    } catch (err) {
        // Explicit timeout detection — gives a clear log message rather than
        // a generic axios error when OpenAI takes longer than 45 seconds.
        if (err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT') {
            throw new Error('OpenAI API timed out after 45s');
        }
        throw new Error('OpenAI API network error: ' + (err.message || err.code));
    }

    // ----------------------------------------------------------------
    // Handle HTTP-level errors from OpenAI
    // ----------------------------------------------------------------
    if (response.status !== 200) {
        const errDetail = JSON.stringify(response.data || '').slice(0, 300);
        throw new Error(`OpenAI API Error: ${response.status} ${errDetail}`);
    }

    const aiData = response.data;

    if (
        !aiData ||
        !aiData.choices ||
        !aiData.choices[0] ||
        !aiData.choices[0].message ||
        !aiData.choices[0].message.content
    ) {
        throw new Error('Unexpected response format from OpenAI.');
    }

    // ----------------------------------------------------------------
    // Parse JSON — strip markdown fences OpenAI sometimes adds despite
    // json_object mode. Matches WordPress snippet behavior.
    // ----------------------------------------------------------------
    let rawContent = aiData.choices[0].message.content.trim();

    if (rawContent.startsWith('```json')) rawContent = rawContent.slice(7);
    if (rawContent.startsWith('```'))     rawContent = rawContent.slice(3);
    if (rawContent.endsWith('```'))       rawContent = rawContent.slice(0, -3);
    rawContent = rawContent.trim();

    let evaluationData;
    try {
        evaluationData = JSON.parse(rawContent);
    } catch (_) {
        throw new Error('AI returned invalid JSON: ' + rawContent.slice(0, 200));
    }

    if (!evaluationData || typeof evaluationData !== 'object') {
        throw new Error('AI returned empty or non-object JSON.');
    }

    return evaluationData;
}


module.exports = { callOpenAI };
