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
    "foundational_governance": "",
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
  - what_we_found: 1\u20132 short sentences — MUST describe what was specifically found, not a generic template
  - why_it_matters: 1 sentence
  - next_step: 1 sentence starting with an action verb

OBSERVABLE EVIDENCE DESCRIPTION STANDARD (MANDATORY):
- what_we_found fields MUST describe what was actually found in the evidence, not restate a gap.
- NEVER use these generic templates in what_we_found:
  "Governance intent is established in publicly accessible policy materials..."
  "Partial governance documentation was identified in accessible sources..."
  "Published materials confirm that governance intent exists for this criterion..."
  "Policy-level documentation addressing this criterion was identified..."
- INSTEAD describe the specific evidence type found. Examples:
  BAD: "Governance intent is established in publicly accessible policy materials on the company's website."
  GOOD: "A published scoring methodology covering six governance pillars was identified on the company's website."
  BAD: "Partial governance documentation was identified in accessible sources."
  GOOD: "The company's published rating framework addresses accountability structures but does not document a corrective action process."
- For improvement areas: what_we_found must name the specific gap, not describe the absence of a template.
  BAD: "No AI-specific risk assessment, safety framework, or harm mitigation documentation was identified."
  GOOD: "The published governance framework defines safety as a scored pillar but does not include a published risk assessment or harm mitigation process."

STRENGTHS:
- 2\u20133 items minimum
- Must be grounded in the evidence data provided
- Must name the specific evidence that constitutes the strength — not generic praise

IMPROVEMENT AREAS:
- 3\u20135 items
- Each must include what_we_found, why_it_matters, what_to_do_next
- what_to_do_next must start with an action verb
- No sentence over 20 words
- what_we_found must describe the specific gap, not use generic absence language

ACTION PLAN:
- immediate_actions: 0\u201330 days
- near_term_improvements: 30\u201390 days
- long_term_strengthening: 90+ days
- Each item is a plain string \u2014 clear and practical

CONFIDENCE EXPLANATION:
- 3\u20134 sentences
- Must explain that confidence reflects evidence visibility, not internal practice quality
- Use these calibration templates based on evidence depth:
  FOUNDATIONAL ONLY (methodology/framework found, no operational execution evidence):
    "Evidence confidence reflects the visibility of publicly available governance documentation.
    Published governance methodology and framework documentation was found, supporting foundational
    practices. Confidence is moderate because execution evidence — monitoring records, enforcement
    logs, and operational proof — was not identified in public sources. This does not mean those
    practices are absent internally; it means they have not yet been made publicly verifiable."
  POLICY LEVEL (policy documents found, no execution or validation):
    "Evidence confidence reflects how much publicly available documentation was found and verified.
    Policy-level governance documentation was identified, but no operational execution evidence or
    external validation was confirmed. Higher confidence requires published processes, monitoring
    records, or independent audits — not just stated commitments."
  STRONG (policy + execution + validation found):
    "Evidence confidence reflects the depth and breadth of publicly verifiable governance documentation.
    Policy commitments, operational processes, and external validation evidence were all identified.
    This level of confidence reflects comprehensive public documentation, not just stated intent."

EVIDENCE SUMMARY:
- core_governance: one of: Strong | Emerging | Limited | None
- operational_evidence: one of: Strong | Emerging | Limited | None
- external_validation: one of: Strong | Limited | None
- foundational_governance: one of: Strong | Emerging | Limited | None
  - Strong: published governance methodology, evaluation architecture, or accountability
    framework with measurable structure found across multiple pages with distinct concepts
  - Emerging: some governance methodology language present but limited in scope, depth,
    or page coverage (single page or single concept domain)
  - Limited: governance intent visible but no structured methodology published
  - None: no foundational governance evidence found
- summary: 1 short sentence

CERTIFICATION STATEMENT:
- 2\u20133 sentences
- Neutral and professional
- MUST use two-tier credibility language based on evidence depth:
  FOUNDATIONAL ONLY: "This assessment identified published governance methodology and framework
    documentation. Certification requires evidence that governance commitments are being executed
    and monitored — not just defined. Publishing operational evidence and inviting independent
    validation are the clearest paths to certification readiness."
  POLICY LEVEL: "Publicly available governance documentation establishes intent across key pillars.
    Certification requires a minimum verified score of 70 with documented evidence of governance
    in practice — not just policy statements. Strengthening public documentation of processes,
    outcomes, and accountability structures will advance certification readiness."
  CERTIFIED: "This organisation has demonstrated publicly verifiable governance practices across
    the HAI pillars at the level required for certification. Maintaining and strengthening this
    documentation — and seeking independent validation — will sustain certification standing."
- Do NOT use: "encouraging progress", "continued improvement is encouraged", or other generic filler

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
- Ensure executive_summary, confidence_explanation, and certification_statement do NOT use the word "signals"
- Ensure NO what_we_found field uses the generic boilerplate templates listed in OBSERVABLE EVIDENCE DESCRIPTION STANDARD
- Ensure confidence_explanation uses the calibration template appropriate to the evidence depth
- Ensure certification_statement uses the two-tier credibility language appropriate to evidence depth
- Ensure strengths name specific evidence — not generic praise like "commitment to responsible AI"`;


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
// FOUNDATIONAL GOVERNANCE TEXT PATTERNS
//
// Recognises published governance methodology, evaluation architecture,
// and accountability structure — the kind of governance artefacts a
// serious early-stage organisation produces before it has audit
// infrastructure.
//
// Design rules:
//  - Every pattern requires multi-word structural vocabulary.
//    Single-word sentiment ("responsible", "accountable") does NOT match.
//  - Generic marketing phrases ("we care about AI ethics", "human-centered
//    values") do NOT match any pattern here.
//  - Each pattern is annotated with a CONCEPT DOMAIN used by the
//    multi-page independence + conceptual diversity check.
//
// Concept domains:
//   METHODOLOGY    — evaluation systems, scoring, measurement structure
//   ACCOUNTABILITY — structural accountability and oversight architecture
//   FRAMEWORK      — published governance structures and taxonomies
//   DEPLOYMENT     — operational governance intent for AI deployment
//   ALIGNMENT      — human-alignment with operational structure
//   CERTIFICATION  — certification logic and formal evaluation standards
// ---------------------------------------------------------------
const FOUNDATIONAL_GOVERNANCE_PATTERNS = [
    // METHODOLOGY domain
    { pattern: /scoring[\s\-_]methodology/i,                                                              domain: 'METHODOLOGY'    },
    { pattern: /evidence[\s\-_]based[\s\-_]scoring/i,                                                    domain: 'METHODOLOGY'    },
    { pattern: /alignment[\s\-_]scoring/i,                                                                domain: 'METHODOLOGY'    },
    { pattern: /ai[\s\-_]measurement/i,                                                                   domain: 'METHODOLOGY'    },
    { pattern: /evaluation[\s\-_](?:framework|architecture|methodology)/i,                                domain: 'METHODOLOGY'    },
    // ACCOUNTABILITY domain
    { pattern: /accountability[\s\-_]architecture/i,                                                      domain: 'ACCOUNTABILITY' },
    { pattern: /independent[\s\-_]accountability/i,                                                       domain: 'ACCOUNTABILITY' },
    { pattern: /governance[\s\-_]taxonomy/i,                                                              domain: 'ACCOUNTABILITY' },
    // FRAMEWORK domain
    { pattern: /governance[\s\-_](?:architecture|framework)/i,                                            domain: 'FRAMEWORK'      },
    { pattern: /governance[\s\-_]playbook/i,                                                              domain: 'FRAMEWORK'      },
    { pattern: /transparency[\s\-_]framework/i,                                                           domain: 'FRAMEWORK'      },
    // DEPLOYMENT domain
    { pattern: /responsible[\s\-_](?:ai[\s\-_])?deployment[\s\-_](?:methodology|framework|standards?)/i, domain: 'DEPLOYMENT'     },
    { pattern: /ethical[\s\-_]infrastructure/i,                                                           domain: 'DEPLOYMENT'     },
    // ALIGNMENT domain
    { pattern: /human[\s\-_]alignment[\s\-_](?:principles?|framework|scoring|index)/i,                   domain: 'ALIGNMENT'      },
    { pattern: /measurable[\s\-_]standards?/i,                                                            domain: 'ALIGNMENT'      },
    // CERTIFICATION domain
    { pattern: /certification[\s\-_]methodology/i,                                                        domain: 'CERTIFICATION'  },
];

// URL slugs that suggest foundational governance methodology pages.
// Only counted when isBodyConfirmed returns true (same gate as all other signals).
const FOUNDATIONAL_GOVERNANCE_URL_SLUGS = [
    '/methodology', '/scoring', '/framework', '/certification',
    '/governance-framework', '/accountability-framework',
    '/trust-framework', '/alignment', '/hai-score',
    '/about/methodology', '/about/governance', '/responsible-deployment',
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
// hit (URL wins first; text patterns skip if already matched).\n// This prevents double-counting \"responsible-ai\" URL + body text.
// ---------------------------------------------------------------
//
// Signal quality classification
// ──────────────────────────────
// Each URL signal is classified as either 'confirmed' or 'surface':
//
//   confirmed — the URL slug was detected AND the content block
//               immediately following that URL header in scrapedText
//               contains real body text (not a stub annotation).
//               These count at full weight in classifySignalTier().
//
//   surface   — the URL slug was detected BUT the content block is
//               a stub: [page restricted], [page not retrieved],
//               [page empty], [page low-value], [page capped], etc.
//               The governance path exists and was attempted, but body
//               content never reached OpenAI. These count at reduced
//               weight (0.4) in classifySignalTier().
//
// Text-body matches (source: 'text') are always confirmed — they
// matched real body content by definition.
//
// The distinction is used only in calibration tiering — it does NOT
// affect GPT rubric scoring, confidence, or the evaluation gate.
// ---------------------------------------------------------------

// Stub annotation prefixes written by scraper.js for blocked/empty pages.
// Any content block whose trimmed text starts with one of these is a stub.
const STUB_PREFIXES = [
    '[page restricted',
    '[page not retrieved',
    '[page empty',
    '[page low-value',
    '[page capped',
    '[fallback evaluation',
    '[homepage:',
];

/**
 * Given the full scrapedText and a URL, returns true if the content
 * block for that URL contains real body text (not a stub annotation).
 */
function isBodyConfirmed(scrapedText, url) {
    // Find the header for this URL
    const escapedUrl = url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const headerRe = new RegExp(
        '---\\s*Content from\\s+' + escapedUrl + '\\s*---\\s*([\\s\\S]*?)(?:---\\s*Content from|$)',
        'i'
    );
    const m = scrapedText.match(headerRe);
    if (!m || !m[1]) return false;
    const block = m[1].trim().toLowerCase();
    if (!block) return false;
    return !STUB_PREFIXES.some(prefix => block.startsWith(prefix.toLowerCase()));
}

function detectGovernanceSignals(scrapedText) {
    if (!scrapedText || typeof scrapedText !== 'string') {
        return { high_signals: 0, medium_signals: 0, low_signals: 0, enterprise_signals: 0, matched_phrases: [] };
    }

    const matched = [];
    let high = 0, medium = 0, low = 0, enterprise = 0;
    let confirmed_high = 0, surface_high = 0;  // signal quality split

    // ── Pass 1: URL slug classification ──────────────────────────
    const urls = [];
    const urlHeaderRe = /---\s*Content from\s+(https?:\/\/\S+?)\s*---/gi;
    let m;
    while ((m = urlHeaderRe.exec(scrapedText)) !== null) {
        urls.push(m[1].toLowerCase());
    }

    const urlMatchedConcepts = new Set();

    for (const url of urls) {
        const bodyConfirmed = isBodyConfirmed(scrapedText, url);

        // ── Score-integrity gate ──────────────────────────────────────────────
        // URL slug matching is split into two tracks:
        //
        //   CONFIRMED (bodyConfirmed=true): real body content was retrieved for
        //   this URL. The slug match counts toward high/medium/enterprise/low
        //   signal counts and therefore toward tier, calibration, and score.
        //
        //   UNCONFIRMED (bodyConfirmed=false): the URL was attempted (a stub line
        //   exists in combined_text) but the page returned a wall, redirect,
        //   timeout, or empty body. The slug is recorded in matched_phrases with
        //   confirmed=false for logging and the frontend appendix ("Attempted
        //   source / no evidence found"), but it does NOT increment any signal
        //   counter and does NOT contribute to tier or calibration.
        //   surface_high is still tracked for diagnostic logging only.
        //
        // Rationale: FORCED_PATHS generates stub lines for ~30 governance paths
        // on every run. Without this gate, a company whose entire site is
        // behind a firewall can reach Tier 2-3 purely from generated path stubs
        // — the same integrity problem as generic Semantic Scholar papers.
        // ─────────────────────────────────────────────────────────────────────

        // High: AI-specific slugs
        for (const slug of HIGH_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('high:' + slug)) {
                urlMatchedConcepts.add('high:' + slug);
                if (bodyConfirmed) {
                    high++;
                    confirmed_high++;
                } else {
                    // Diagnostic only — does not count toward score
                    surface_high++;
                }
                matched.push({ tier: 'high', phrase: slug + ' (url)', source: 'url', confirmed: bodyConfirmed });
                break;
            }
        }
        // Medium: structured transparency slugs
        for (const slug of MEDIUM_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('medium:' + slug)) {
                urlMatchedConcepts.add('medium:' + slug);
                if (bodyConfirmed) {
                    medium++;
                }
                matched.push({ tier: 'medium', phrase: slug + ' (url)', source: 'url', confirmed: bodyConfirmed });
                break;
            }
        }
        // Enterprise: non-AI governance slugs (counts toward medium_signals only if confirmed)
        for (const slug of ENTERPRISE_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('enterprise:' + slug)) {
                urlMatchedConcepts.add('enterprise:' + slug);
                if (bodyConfirmed) {
                    enterprise++;
                    medium++;  // enterprise signals count as medium so evaluation gate passes
                }
                matched.push({ tier: 'enterprise', phrase: slug + ' (url)', source: 'url', confirmed: bodyConfirmed });
                break;
            }
        }
        // Low: generic legal slugs
        for (const slug of LOW_URL_SLUGS) {
            if (url.includes(slug) && !urlMatchedConcepts.has('low:' + slug)) {
                urlMatchedConcepts.add('low:' + slug);
                if (bodyConfirmed) {
                    low++;
                }
                matched.push({ tier: 'low', phrase: slug + ' (url)', source: 'url', confirmed: bodyConfirmed });
                break;
            }
        }
    }

    // ── Pass 2: text-body pattern matching ───────────────────────
    // Text matches are always 'confirmed' — they matched real body content.
    //
    // IMPORTANT: strip the "--- Content from URL ---" header lines before
    // running text patterns. Without this, patterns like /responsible[\s-_]ai/
    // match the URL string "responsible-ai" inside a stub header even when
    // the page body is [page not retrieved] — inflating high_signals from
    // purely generated paths with zero body content.
    //
    // We build bodyOnlyText by removing every section that is stub-only:
    // a stub section is one where the content block starts with a STUB_PREFIX.
    // Confirmed-body sections are kept intact for text pattern matching.
    const bodyOnlyText = (() => {
        // Split on section headers, process each block, rejoin confirmed blocks only
        const sectionRe = /---\s*Content from\s+https?:\/\/\S+?\s*---/gi;
        const parts = scrapedText.split(sectionRe);
        // parts[0] is preamble before the first header (fallback annotations etc.)
        // Strip that too — it may contain [Fallback evaluation] which can hold path names
        const confirmedParts = [];
        // We need the headers to check isBodyConfirmed; rebuild via matchAll
        const headers = [...scrapedText.matchAll(/---\s*Content from\s+(https?:\/\/\S+?)\s*---/gi)];
        headers.forEach((hdr, i) => {
            const url   = hdr[1];
            const block = parts[i + 1] || ''; // parts[0] is pre-header preamble
            const blockTrimmed = block.trim().toLowerCase();
            const isStub = STUB_PREFIXES.some(pfx => blockTrimmed.startsWith(pfx.toLowerCase()));
            if (!isStub) {
                confirmedParts.push(block);
            }
        });
        return confirmedParts.join('\n');
    })();

    for (const p of HIGH_TEXT_PATTERNS) {
        const hit = bodyOnlyText.match(p);
        if (hit) {
            const phrase = hit[0].trim().toLowerCase();
            const alreadyCounted = matched.some(
                x => x.tier === 'high' && x.source === 'url' &&
                     phrase.replace(/[\s_]/g, '-').includes(x.phrase.replace(' (url)', ''))
            );
            if (!alreadyCounted) {
                high++;
                confirmed_high++;  // text matches are always confirmed
                matched.push({ tier: 'high', phrase, source: 'text', confirmed: true });
            }
        }
    }
    for (const p of MEDIUM_TEXT_PATTERNS) {
        const hit = bodyOnlyText.match(p);
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
        const hit = bodyOnlyText.match(p);
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
        const hit = bodyOnlyText.match(p);
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

    // ── Pass 3: Foundational governance pattern matching ─────────────────
    //
    // Foundational governance signals recognise published methodology,
    // evaluation architecture, and accountability structure. They require
    // multi-word structural phrases — generic sentiment vocabulary does
    // not match.
    //
    // Gate rules (enforced below, after all matches are collected):
    //
    //   medium_signals contribution:
    //     Requires BOTH page diversity (matches across >= 2 distinct URLs)
    //     AND concept diversity (matches span >= 2 distinct concept domains).
    //     Single dense pages, and two pages repeating the same concept, do
    //     not qualify. Contributes at most +1 to medium_signals regardless
    //     of match count.
    //
    //   high_signals contribution:
    //     A foundational match on a page that also contains at least one
    //     existing HIGH_TEXT_PATTERNS match on the same confirmed page.
    //     Contributes at most +1 to high_signals.
    //     Rationale: HIGH co-occurrence confirms the page is unambiguously
    //     a governance methodology page, not a general about-page that
    //     incidentally contains structural vocabulary.
    //
    // All matches run against bodyOnlyText (confirmed body content only).
    // Deduplication: a phrase already captured by HIGH or MEDIUM patterns
    // does not also count as foundational.

    // Build a per-page HIGH-match index so the HIGH co-occurrence check
    // can be done efficiently.
    const highMatchedPages = new Set();
    for (const m of matched) {
        if (m.tier === 'high' && m.source === 'text' && m.pageUrl) {
            highMatchedPages.add(m.pageUrl);
        }
    }
    // Also index HIGH url-confirmed matches by their URL
    for (const m of matched) {
        if (m.tier === 'high' && m.source === 'url' && m.confirmed && m.phrase) {
            // Reconstruct the page URL from the slug phrase embedded in the match
            // We cannot recover the full URL here, so we use a broader check below.
        }
    }

    // Walk bodyOnlyText section by section to track which page each match comes from.
    // We rebuild a per-page map: pageUrl → { matches: [{phrase, domain}] }
    const foundationalByPage = {};  // pageUrl → { phrases: Set, domains: Set }
    const seenFoundational = new Set();

    const sectionRe2 = /---\s*Content from\s+(https?:\/\/\S+?)\s*---/gi;
    const sectionParts2 = scrapedText.split(/---\s*Content from\s+https?:\/\/\S+?\s*---/gi);
    const sectionHeaders2 = [...scrapedText.matchAll(/---\s*Content from\s+(https?:\/\/\S+?)\s*---/gi)];

    // Build confirmed-body page text map
    const confirmedPageTexts = {};
    sectionHeaders2.forEach((hdr, i) => {
        const pageUrl2 = hdr[1];
        const block2   = sectionParts2[i + 1] || '';
        const blockTrimmed2 = block2.trim().toLowerCase();
        const isStub2 = STUB_PREFIXES.some(pfx => blockTrimmed2.startsWith(pfx.toLowerCase()));
        if (!isStub2) {
            confirmedPageTexts[pageUrl2] = block2;
        }
    });

    // Also check whether a page's content contains a HIGH text pattern
    // (used for the HIGH co-occurrence check).
    const pagesWithHighMatch = new Set();
    for (const [pageUrl2, pageText2] of Object.entries(confirmedPageTexts)) {
        for (const hp of HIGH_TEXT_PATTERNS) {
            if (hp.test(pageText2)) {
                pagesWithHighMatch.add(pageUrl2);
                break;
            }
        }
    }

    // Now match foundational patterns against each confirmed page
    let foundationalHighAdded = false;
    for (const [pageUrl2, pageText2] of Object.entries(confirmedPageTexts)) {
        for (const { pattern, domain } of FOUNDATIONAL_GOVERNANCE_PATTERNS) {
            const hit2 = pageText2.match(pattern);
            if (!hit2) continue;
            const phrase2 = hit2[0].trim().toLowerCase();

            // Deduplication: skip if already captured by HIGH or MEDIUM pattern
            const alreadyHighOrMedium = matched.some(m =>
                (m.tier === 'high' || m.tier === 'medium') && m.source === 'text' &&
                phrase2.includes(m.phrase.replace(/[\s_]/g, ' '))
            );
            if (alreadyHighOrMedium) continue;
            if (seenFoundational.has(phrase2)) continue;
            seenFoundational.add(phrase2);

            // Record match for this page
            if (!foundationalByPage[pageUrl2]) {
                foundationalByPage[pageUrl2] = { phrases: new Set(), domains: new Set() };
            }
            foundationalByPage[pageUrl2].phrases.add(phrase2);
            foundationalByPage[pageUrl2].domains.add(domain);

            matched.push({ tier: 'foundational', phrase: phrase2, source: 'text', domain, pageUrl: pageUrl2, confirmed: true });

            // HIGH co-occurrence check: foundational match on a page that also has a HIGH match
            if (!foundationalHighAdded && pagesWithHighMatch.has(pageUrl2)) {
                high++;
                confirmed_high++;
                foundationalHighAdded = true;
                console.log(`[report-generator] Foundational HIGH co-occurrence on ${pageUrl2}: "${phrase2}"`);
            }
        }
    }

    // Aggregate foundational stats
    const foundational_governance = seenFoundational.size;
    const allFoundationalDomains = new Set();
    const allFoundationalPages   = new Set(Object.keys(foundationalByPage));
    Object.values(foundationalByPage).forEach(p => p.domains.forEach(d => allFoundationalDomains.add(d)));

    // Multi-page + concept diversity gate for medium_signals contribution.
    // Requires: >= 2 distinct confirmed pages AND >= 2 distinct concept domains.
    const meetsPageDiversity    = allFoundationalPages.size >= 2;
    const meetsConceptDiversity = allFoundationalDomains.size >= 2;
    if (meetsPageDiversity && meetsConceptDiversity) {
        medium++;
        console.log(`[report-generator] Foundational MEDIUM gate passed: pages=${allFoundationalPages.size} domains=[${[...allFoundationalDomains].join(',')}]`);
    } else if (foundational_governance > 0) {
        console.log(`[report-generator] Foundational gate NOT met: pages=${allFoundationalPages.size} domains=${allFoundationalDomains.size} — framing only, no medium_signals contribution`);
    }

    return {
        high_signals:           high,
        medium_signals:         medium,  // includes enterprise contributions
        low_signals:            low,
        enterprise_signals:     enterprise,
        foundational_governance,          // new counter — used for maturity-aware framing
        foundational_pages:     allFoundationalPages.size,
        foundational_domains:   [...allFoundationalDomains],
        matched_phrases:        matched,
        // Signal quality split — used by classifySignalTier() only.
        // confirmed_high: URL slug + real body content retrieved.
        // surface_high:   URL slug only; body was stub/wall/blocked.
        confirmed_high,
        surface_high,
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
// GOVERNANCE MATURITY CLASSIFICATION
//
// Maps stage + size inputs to a governance maturity label:
//   emerging     — early-stage organisations building governance foundations
//   scaling      — growth-stage organisations developing operational evidence
//   institutional — mature organisations with full governance infrastructure expected
//
// Uses governance maturity terminology, not financial stage terminology.
// When stage and size conflict, the more conservative (higher maturity)
// classification wins — prevents large organisations claiming emerging status.
// ---------------------------------------------------------------
function classifyGovernanceMaturity(scrapeContext) {
    const ctx   = scrapeContext || {};
    const stage = (ctx.stage || '').toLowerCase().trim();
    const size  = (ctx.size  || '').toLowerCase().trim();

    // Stage → maturity mapping
    let stageMaturity = 'scaling';  // default conservative middle
    if (/startup|early.stage|seed|pre.seed/.test(stage))       stageMaturity = 'emerging';
    else if (/growth|series.a|series.b|scale.?up/.test(stage)) stageMaturity = 'scaling';
    else if (/enterprise|public|large|institutional/.test(stage)) stageMaturity = 'institutional';

    // Size → maturity override (prevents large orgs claiming emerging status)
    let sizeMaturity = null;
    if (/^1.10$|^11.50$/.test(size))   sizeMaturity = 'emerging';
    else if (/^51.200$/.test(size))     sizeMaturity = 'scaling';
    else if (/200\+|1000\+/.test(size)) sizeMaturity = 'institutional';
    // Also catch numeric ranges like "200+" written differently
    const sizeNum = parseInt(size.replace(/[^0-9]/g, ''), 10);
    if (!isNaN(sizeNum)) {
        if (sizeNum >= 200 && sizeMaturity !== 'institutional') sizeMaturity = 'institutional';
        else if (sizeNum >= 51 && sizeMaturity === 'emerging')  sizeMaturity = 'scaling';
    }

    // Conservative merge: take the higher maturity when they conflict
    const MATURITY_ORDER = { emerging: 0, scaling: 1, institutional: 2 };
    if (sizeMaturity && MATURITY_ORDER[sizeMaturity] > MATURITY_ORDER[stageMaturity]) {
        return sizeMaturity;
    }
    return stageMaturity;
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

    // ── Signal quality weighting ──────────────────────────────────────────────
    // Only confirmed signals (bodyConfirmed=true) count toward tier.
    // surface_high is logged for diagnostics only — unconfirmed URL stubs
    // were excluded from signal counts in detectGovernanceSignals().
    // Text-body matches are always confirmed by definition.
    const confirmedH = typeof signals.confirmed_high === 'number' ? signals.confirmed_high : high_signals;
    const surfaceH   = typeof signals.surface_high   === 'number' ? signals.surface_high   : 0;
    const eff_high   = confirmedH;  // surface signals no longer inflate tier
    const maxTier    = confirmedH === 0 ? 2 : 4;

    // ── Tier 4: high signals AND broad pillar coverage ────────────────────────
    // Tier 3.5 downgrade: qualifies for Tier4 by signal count but confidence is
    // low, suggesting URL slugs exist without confirmed deep body evidence.
    if (eff_high >= 4 && pillarsWithEvidence >= 4 && maxTier >= 4) {
        const conf = typeof confPercent === 'number' ? confPercent : 100;
        if (conf < EVIDENCE_CAP_THRESHOLD) {
            return { tier: 3, pillarsWithEvidence, downgraded: true };
        }
        return { tier: 4, pillarsWithEvidence, downgraded: false };
    }
    if (eff_high >= 3 && maxTier >= 3) return { tier: 3, pillarsWithEvidence, downgraded: false };
    if (eff_high >= 1)                  return { tier: Math.min(2, maxTier), pillarsWithEvidence, downgraded: false };
    if (medium_signals >= 1)            return { tier: 1, pillarsWithEvidence, downgraded: false };
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
    const fg = signalProfile.foundational_governance || 0;
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
    // Foundational governance only — methodology and architecture present but no AI-specific signals
    // This handles governance-focused emerging organisations whose methodology pages are
    // detected by the foundational gate but whose content hasn't yet generated standard high signals.
    if (fg >= 2 && total === 0) {
        return {
            evidence_language: 'Published governance methodology identified',
            pillar_baseline:   'Governance methodology and accountability architecture documentation is publicly available. Publishing explicit AI-specific governance commitments would strengthen this assessment.',
            forbidden_phrases: ['no governance', 'absence of governance', 'no evidence found', 'governance signals', 'signals identified'],
            executive_frame:   'Published governance methodology and accountability architecture documentation was found. The assessment reflects the depth and operational coverage of publicly available governance documentation.',
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



function computeCalibration(rawScore, tier, pillarsWithEvidence, confPercent, downgraded) {
    if (tier === 0) return { calibrated_score: rawScore, uplift_applied: 0, multi_pillar_bonus: 0, tier, downgraded: false };
    let uplift = UPLIFT_MIDPOINTS[tier] || 0;

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
function buildUserPrompt(evaluationData, scrapedText, signalProfile, isPartial, scrapeContext) {
    const LEVEL_LABELS = { 1: 'Not Present', 2: 'Initial', 3: 'Developing', 4: 'Established', 5: 'Advanced' };
    let pillarSummaries = '';
    let totalItems = 0, pillarsWithEvidence = 0;

    // Governance maturity classification — used for maturity-aware framing
    const governanceMaturity = classifyGovernanceMaturity(scrapeContext || {});
    const fg = (signalProfile && signalProfile.foundational_governance) || 0;
    const fgPages   = (signalProfile && signalProfile.foundational_pages)   || 0;
    const fgDomains = (signalProfile && signalProfile.foundational_domains) || [];

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
Foundational governance methodology items: ${fg} (across ${fgPages} pages, domains: ${fgDomains.join(', ') || 'none'})
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

    // Maturity-aware instruction block.
    // Activates only for 'emerging' organisations with >= 2 foundational governance items.
    // For all other maturity levels this block is empty — no framing change.
    const maturityNote = (governanceMaturity === 'emerging' && fg >= 2) ? `
GOVERNANCE MATURITY CONTEXT (MANDATORY — applies to this evaluation):
- This organisation is at the EMERGING stage of governance maturity.
- Enterprise-only artefacts listed below are NOT expected at this stage. Do NOT penalise
  their absence or list them as immediate actions. They belong in long_term_strengthening only.
  - SEC filings, proxy statements, investor governance filings
  - Formal third-party audit reports and ISO certifications
  - Board committee documentation and board oversight minutes
  - Enterprise compliance reports and SOX documentation
- Instead, evaluate the quality of: published governance methodology, accountability architecture,
  measurable standards, scoring frameworks, and certification logic.
- Foundational governance evidence items found: ${fg} (across ${fgPages} distinct pages, concept domains: ${fgDomains.join(', ')})
- The confidence_explanation MUST include this sentence (verbatim or closely paraphrased, max 2 sentences):
  "At this stage of organisational maturity, the evaluation emphasised published governance methodology
  and accountability architecture rather than enterprise-scale audit infrastructure. Missing enterprise
  artefacts such as formal audits, ISO certifications, and board committee documentation are not treated
  as governance failures at this maturity level."
- Do NOT repeat the maturity context in executive_summary or certification_statement — once only, in confidence_explanation.
- Do NOT create a new section or heading for this context — embed it in confidence_explanation.
- evidence_summary.foundational_governance must be "Emerging" or "Strong" given the evidence found.
` : `
GOVERNANCE MATURITY CONTEXT:
- Governance maturity level for this organisation: ${governanceMaturity.toUpperCase()}
- Foundational governance methodology items found: ${fg}
${governanceMaturity === 'institutional' ? '- This is an institutional organisation. Enterprise-scale governance artefacts (audits, certifications, board oversight) are expected and their absence should be noted as gaps.' : ''}
`;

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
${maturityNote}
${partialNote}` : `
INTERPRETATION FRAME:
- Limited publicly available governance documentation was found. Use "Limited publicly available governance documentation" in evidence_summary.
- Do not claim complete absence of governance — state that public documentation is limited.
${maturityNote}
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
    const signals        = detectGovernanceSignals(scrapedText);
    const ctx            = scrapeContext || {};
    // isPartial is true when:
    //   - scraper flagged a partial scrape (homepage unreachable)
    //   - limited_access: total text under 1 000 chars
    //   - content_empty: text exceeded that threshold but was almost entirely
    //     scraper stubs — real governance content < 500 chars.
    //     Without this flag, stub-heavy pages pass as valid, OpenAI receives no
    //     usable text, returns all criteria at level 1, and confPercent = 100.
    //   - scrapeStatus 'limited': scraper returned content but hit >= 3 redirect
    //     walls — real governance pages were not reached.
    const isPartial      = !!(ctx.partialScrape || ctx.limitedAccess || ctx.contentEmpty ||
                               ctx.scrapeStatus === 'limited');
    const evalState      = determineEvaluationState(signals, isPartial);

    // ── Access-limited classification ─────────────────────────────────────────
    // A run is access_limited when no confirmed body content reached OpenAI AND
    // GPT-4o found no rubric evidence. Covers homepage timeouts, firewall blocks,
    // and pure stub runs. These still produce a report but are excluded from
    // benchmark averages and receive distinct labelling.
    const rawScoreProxyForClassification = deriveRawScoreProxy(evaluationData);
    const confirmedHighCount = typeof signals.confirmed_high === 'number' ? signals.confirmed_high : signals.high_signals;
    const isAccessLimited    = (confirmedHighCount === 0 && rawScoreProxyForClassification === 0);

    console.log(`[report-generator] Signals — high:${signals.high_signals} medium:${signals.medium_signals} enterprise:${signals.enterprise_signals||0} foundational:${signals.foundational_governance||0}(pages:${signals.foundational_pages||0} domains:${(signals.foundational_domains||[]).join(',')}) low:${signals.low_signals} confirmed_high:${signals.confirmed_high||0} surface_high(diagnostic_only):${signals.surface_high||0} state:${evalState} partial:${isPartial} access_limited:${isAccessLimited}`);

    // Step 2: Insufficient evidence gate — only fires when no signals at all,
    // even after fallback URL stubs are included in scrapedText.
    if (evalState === 'insufficient_evidence') {
        console.log('[report-generator] insufficient_evidence — returning structured refusal');
        return buildInsufficientEvidenceResponse(signals);
    }

    // Step 3: Tier and calibration inputs
    // confPercent is not available at the backend — the exact value is computed
    // in bundle.js from the rubric evidence items after OpenAI scoring.
    // We therefore do NOT compute a calibrated_score here.
    // Instead we return the tier, uplift midpoint, and pillar bonus so that
    // bundle.js can perform the single authoritative calibration with the real
    // confPercent.  This eliminates the two-run divergence that was producing
    // four different observed offsets for the same tier.
    const { tier, pillarsWithEvidence, downgraded } = classifySignalTier(signals, evaluationData, null);
    const rawScoreProxy  = deriveRawScoreProxy(evaluationData);
    const upliftMidpoint = UPLIFT_MIDPOINTS[tier] || 0;
    const multiPillarBonus = (pillarsWithEvidence >= 4 && !downgraded) ? 8 : 0;
    console.log(`[report-generator] Tier:${tier} rawProxy:${rawScoreProxy} upliftMidpoint:${upliftMidpoint} partial:${isPartial}`);

    // Step 4: Generate narrative report
    const userPrompt = buildUserPrompt(evaluationData, scrapedText, signals, isPartial, ctx);

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
    // access_limited overrides partial_evaluation when no body content was confirmed
    const finalEvalState = isAccessLimited
        ? 'access_limited'
        : (evalState === 'partial_evaluation') ? 'partial_evaluation' : 'valid';

    report.evaluation_state  = finalEvalState;
    report.benchmark_eligible = !isAccessLimited;

    report.signal_profile   = {
        high_signals:           signals.high_signals,
        medium_signals:         signals.medium_signals,
        low_signals:            signals.low_signals,
        foundational_governance: signals.foundational_governance || 0,
        foundational_pages:      signals.foundational_pages      || 0,
        foundational_domains:    signals.foundational_domains    || [],
        tier,
        confirmed_high:          signals.confirmed_high || 0,
        surface_high:            signals.surface_high   || 0,
        matched_phrases:         signals.matched_phrases.slice(0, 10)
    };
    report.governance_maturity = classifyGovernanceMaturity(ctx);
    report.calibration = {
        tier,
        uplift_midpoint:        upliftMidpoint,
        multi_pillar_bonus:     multiPillarBonus,
        raw_score_proxy:        rawScoreProxy,
        score_cap:              SCORE_CAP,
        evidence_cap_threshold: EVIDENCE_CAP_THRESHOLD,
        evidence_cap_value:     EVIDENCE_CAP_VALUE,
        downgraded:             downgraded,
        partial_evaluation:     isPartial
    };

    // ── Access-limited report overrides ───────────────────────────────────────
    // When confirmed_high === 0 and raw_score === 0, the report was produced from
    // stub content only (homepage timeout, firewall block, etc.). Override key
    // framing fields so the PDF clearly communicates the assessment limitation
    // and prompts the user to resubmit with direct governance URLs.
    // The pillar narratives and gap analysis from GPT-4o are still included —
    // they provide useful structural guidance even without body content.
    if (isAccessLimited) {
        report.executive_summary =
            'ACCESS-LIMITED ASSESSMENT — This evaluation could not retrieve governance ' +
            'page content from this organisation\'s website. The score below is an ' +
            'access-limited estimate based on detected governance URL structure only, ' +
            'not on verified page content. For a full assessment, re-run using the ' +
            '"Add governance URLs" option and paste direct links to the organisation\'s ' +
            'responsible AI, ethics, or governance pages.';

        report.certification_statement =
            'Full certification assessment requires accessible governance page content. ' +
            'This access-limited run has been excluded from benchmark calculations. ' +
            'Re-run with direct governance URLs to receive a scored, benchmark-eligible assessment.';

        if (report.snapshot) {
            report.snapshot.certification_status = 'Access-Limited — Not Benchmark Eligible';
        }

        console.log('[report-generator] access_limited — report framing overridden, benchmark_eligible=false');
    }

    return report;
}


module.exports = { generatePremiumReport };
