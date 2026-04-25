// ============================================================
// FIX 12 — PROOF-OF-EXECUTION DETECTION
// FILES: src/services/openai.js              (backend — rubric prompt)
//        src/services/supplementary-evidence.js (backend — annotation)
//        bundle.js                           (frontend scoring + PDF)
//
// WHY THIS COMES FIRST IN PHASE 6:
//   HAI certification measures whether human-centred governance
//   is actually practised — not just stated. The difference between
//   an organisation that has written a Responsible AI framework
//   and one that uses it daily is the entire substance of this index.
//
//   Demonstrated practice raises criterion confidence.
//   Undocumented intent — however well written — earns less.
//   This principle applies equally to Trust, Purpose, and Impact
//   as it does to Safety and Accountability.
//
// WHAT THIS DETECTS:
//   Execution artefacts are signals that a practice was carried out,
//   not just planned. They include: quantified outcomes with dates,
//   named roles with recorded decisions, completed audit records,
//   change logs, tested systems, incident resolutions, and
//   published results from ongoing measurement.
//
//   A policy document is the starting point for governance.
//   Execution artefacts are evidence that it is lived.
//
// EXECUTION LEVELS (four tiers):
//   verified   — third-party verified artefact or dated quantified outcome
//   partial    — execution trace without full external verification
//   asserted   — intent language; no artefact evidence
//   none       — policy document only; no execution signals found
// ============================================================


// ══════════════════════════════════════════════════════════════
// SECTION 1: EXECUTION ARTEFACT KEYWORD PATTERNS
// Patterns are grouped by artefact type. Each group maps to
// an execution category with a weight (used in scoring).
// ══════════════════════════════════════════════════════════════

const EXECUTION_KEYWORDS = {
    // Quantified, time-stamped outcomes (strongest execution signal)
    metrics: [
        /\d{1,3}%\s*(reduction|improvement|decrease|increase)/i,
        /\d+\s*(incidents|cases|complaints|audits|reviews)\s*(reported|resolved|completed)/i,
        /in\s*(Q[1-4]|january|february|march|april|may|june|july|august|september|october|november|december)\s*202[0-9]/i,
        /as of\s*(Q[1-4]|[0-9]{4})/i,
        /year-over-year|quarter-on-quarter|monthly trend|annual report/i,
        /measured|quantified|tracked|monitored since/i,
    ],

    // Process execution traces: something happened, not just planned
    process: [
        /approved by|signed off by|reviewed by|audited by/i,
        /ethics (committee|board|panel|review) (met|convened|approved|reviewed)/i,
        /incident (reported|logged|resolved|investigated)/i,
        /change (log|record|audit trail)/i,
        /meeting (minutes|notes|agenda) (published|available|archived)/i,
        /testing (completed|passed|failed|conducted)/i,
        /red team(ing)? (conducted|performed|completed)/i,
        /model card (published|released|updated)/i,
        /datasheets? for datasets?/i,
        /deployed|launched|rolled out|went live/i,
    ],

    // Named roles with recorded decisions (accountability execution)
    control: [
        /chief (ai|ethics|responsible|technology) officer/i,
        /responsible ai (lead|officer|director|team)/i,
        /ai (governance|ethics|safety) (committee|board|council|team)/i,
        /[A-Z][a-z]+ [A-Z][a-z]+,?\s*(VP|Director|Head of|Chief)/i,
        /escalated to|reviewed by (the )?(board|executive|leadership)/i,
    ],

    // Third-party verification artefacts
    audit: [
        /iso (42001|27001|9001)[\s:–\-]*(certified|certification|compliant|audit)/i,
        /soc\s*2?\s*(type\s*i+|audit|report|compliant)/i,
        /independent (audit|review|assessment|evaluation)/i,
        /(external|third.party) (auditor|reviewer|assessor|verifier)/i,
        /certification (awarded|achieved|renewed|maintained)/i,
        /nist (ai\s*rmf|ai risk management|800-)/i,
        /eu ai act (compliant|compliance|assessment|registration)/i,
    ],

    // Published human-outcome results (impact execution)
    impact: [
        /users? (benefited|improved|helped|saved|assisted)\s*:?\s*\d/i,
        /time saved|hours? (saved|reduced|freed)/i,
        /error(s?) (reduced|decreased|eliminated)/i,
        /access(ibility)? (improved|expanded|increased)/i,
        /outcome(s?) (measured|published|reported)/i,
        /impact (report|assessment|evaluation) (published|released|completed)/i,
    ],
};

// Weight per execution category: how strongly does this type of artefact
// evidence indicate that a practice is actually happening?
const EXECUTION_CATEGORY_WEIGHTS = {
    metrics: 1.0,   // hardest to fake; time-stamped numbers
    process: 0.8,   // process traces — real but easier to describe without doing
    control: 0.7,   // named roles — existence doesn't prove active use
    audit:   1.0,   // third-party verification — independently confirmed
    impact:  0.9,   // published human outcomes — central to HAI purpose
};


// ══════════════════════════════════════════════════════════════
// SECTION 2: computeExecutionScore(text)
// Scans text for execution artefact signals.
// Returns { executionLevel, score, signals, categories }
// ══════════════════════════════════════════════════════════════

function computeExecutionScore(text) {
    if (!text) return { executionLevel: 'none', score: 0, signals: [], categories: [] };

    const signals   = [];
    const categories = [];
    let   totalWeight = 0;

    Object.entries(EXECUTION_KEYWORDS).forEach(([category, patterns]) => {
        const categoryMatches = patterns.filter(p => p.test(text));
        if (categoryMatches.length > 0) {
            const weight = EXECUTION_CATEGORY_WEIGHTS[category];
            categories.push(category);
            signals.push(...categoryMatches.map(p => ({ category, pattern: p.source })));
            totalWeight += weight;
        }
    });

    // Determine level
    let executionLevel;
    if (totalWeight === 0) {
        executionLevel = 'none';
    } else if (
        categories.includes('audit') ||
        (categories.includes('metrics') && totalWeight >= 1.8)
    ) {
        executionLevel = 'verified';
    } else if (
        categories.includes('metrics') ||
        (categories.includes('process') && categories.includes('control'))
    ) {
        executionLevel = 'partial';
    } else {
        executionLevel = 'asserted';
    }

    return { executionLevel, score: totalWeight, signals, categories };
}


// ══════════════════════════════════════════════════════════════
// SECTION 3: annotateWithExecutionScore(items, combinedText)
// Enriches each evidence item with execution level and signals.
// Call this after all evidence is assembled in supplementary-evidence.js.
// ══════════════════════════════════════════════════════════════

function annotateWithExecutionScore(items, combinedScrapedText) {
    const globalExecution = computeExecutionScore(combinedScrapedText || '');

    return items.map(item => {
        // Per-item execution: scan the item's own text
        const itemExecution = computeExecutionScore(item.text || '');

        // Take the higher of item-level and global context
        const execLevels = ['none', 'asserted', 'partial', 'verified'];
        const globalIdx  = execLevels.indexOf(globalExecution.executionLevel);
        const itemIdx    = execLevels.indexOf(itemExecution.executionLevel);
        const finalLevel = execLevels[Math.max(globalIdx, itemIdx)];

        // Upgrade role: if we find execution evidence for this item, move 'supports' → 'justifies'
        const upgradedRole = upgradeRoleByExecution(item.role, finalLevel);

        return {
            ...item,
            executionLevel:    finalLevel,
            executionSignals:  itemExecution.signals,
            executionCategories: itemExecution.categories,
            role:              upgradedRole,
        };
    });
}

// A 'supports' item with verified execution may become 'justifies'
// because the combination of source-level support + execution artefact
// together constitute justifying evidence.
function upgradeRoleByExecution(currentRole, executionLevel) {
    if (currentRole === 'contradicts') return currentRole;  // never upgrade contradictions
    if (currentRole === 'supports' && executionLevel === 'verified') return 'justifies';
    return currentRole;
}


// ══════════════════════════════════════════════════════════════
// SECTION 4: detectExecutionGap(criterionState, rubricCriterion, combinedText)
// Returns true when a criterion has policy-level evidence but no
// execution signals. Used to surface "Execution Gap" in PDF output.
// ══════════════════════════════════════════════════════════════

function detectExecutionGap(criterionState, combinedText) {
    const lvl = parseInt(criterionState.level, 10) || 1;

    // Only relevant for criteria that scored based on published claims (level 2+)
    if (lvl < 2) return false;

    // If criteria items include only public_claim / policy types and no metric/audit/control
    const hasOnlyClaimEvidence = criterionState.items.length > 0 &&
        !criterionState.executionLevel ||
        criterionState.executionLevel === 'none' ||
        criterionState.executionLevel === 'asserted';

    const execCheck = computeExecutionScore(combinedText || '');
    return hasOnlyClaimEvidence && execCheck.executionLevel === 'none';
}

function scanExecutionGaps(assessmentState, combinedText) {
    const gaps = [];
    Object.entries(assessmentState).forEach(([critId, state]) => {
        if (detectExecutionGap(state, combinedText)) {
            gaps.push(critId);
        }
    });
    return gaps;
}


// ══════════════════════════════════════════════════════════════
// SECTION 5: OPENAI RUBRIC PROMPT INSTRUCTION
// File: src/services/openai.js
//
// Add OPENAI_EXECUTION_INSTRUCTION to the system prompt sent with
// the 20-criterion rubric evaluation. Instruct GPT-4o to identify
// whether execution artefacts are present for each criterion.
//
// FIND the system prompt string in openai.js (the block that
// instructs GPT-4o how to evaluate the 20 criteria).
// ADD the following instruction block before the criterion list.
// ══════════════════════════════════════════════════════════════

const OPENAI_EXECUTION_INSTRUCTION = `
EXECUTION EVIDENCE INSTRUCTION:
For each criterion, in addition to assigning a level (1–5), assign an
"executionLevel" field from the following values:

  "verified"  — The text contains a third-party verified artefact, a dated
                quantified outcome, or an independent audit result for this
                criterion. Something was done and it is externally confirmed.

  "partial"   — The text contains a process trace, a named individual with a
                recorded decision, or a time-stamped activity log. Something
                was done but it is self-reported without external verification.

  "asserted"  — The text describes intent, policy, or commitment language
                without any artefact that demonstrates the practice has occurred.
                Phrases like "we aim to", "our policy is to", "we are committed
                to" are asserted-only signals.

  "none"      — No evidence of the criterion was detected. The criterion may
                not apply to this organisation, or evidence was not found.

This field must be set for every criterion in your output JSON, alongside
the existing level field. Do not conflate maturity level with execution level.
A company may publish a sophisticated Level 3 policy framework (level: 3,
executionLevel: "asserted") or a simple Level 2 practice that is audited
(level: 2, executionLevel: "verified"). Assess them independently.
`.trim();


// ══════════════════════════════════════════════════════════════
// SECTION 6: EXECUTION BONUS IN CONFIDENCE FORMULA
// Integrates with FIX-8's computeCriterionConfidence().
//
// Add executionBonus(executionLevel) call at the end of
// computeCriterionConfidence() in supplementary-evidence.js.
// ══════════════════════════════════════════════════════════════

function executionBonus(executionLevel) {
    switch (executionLevel) {
        case 'verified':  return 20;   // independently confirmed practice
        case 'partial':   return 10;   // self-reported execution trace
        case 'asserted':  return  0;   // intent only — no bonus
        case 'none':      return -5;   // policy-only signal — modest confidence reduction
        default:          return  0;
    }
}

// In computeCriterionConfidence() (FIX-8 Section 4), at the end, before return:
//   const _execLevel = (evidenceItems[0] && evidenceItems[0].executionLevel) || 'none';
//   const _execBonus = executionBonus(_execLevel);
//   return Math.min(100, Math.max(0, Math.round(totalContribution + scaledBonus + _execBonus)));


// ══════════════════════════════════════════════════════════════
// SECTION 7: PDF — EXECUTION GAP INDICATOR IN CRITERION GRID
// File: bundle.js
// WHERE: printPillarBlock() criterion grid from FIX-4
//
// When a criterion has executionGap === true, add a small "⊘ No
// execution evidence found" indicator in the Top Gap column.
// This is explanatory, not accusatory — it tells the report reader
// that the policy exists but no artefact confirming its use was found.
// ══════════════════════════════════════════════════════════════

// In pdfSummaryContent.push(), add executionGap to critScores items:
//   executionGap:  detectExecutionGap(critState, window.currentScrapedTextPreview || ''),
//   executionLevel: critState.executionLevel || 'none'
//
// In printPillarBlock() criterion grid, after rendering missingTop:
//   if (crit.executionGap) {
//       doc.setFont('helvetica', 'italic'); doc.setFontSize(6);
//       doc.setTextColor(120, 80, 0);  // amber — informational, not alarming
//       doc.text('Policy found; no execution evidence detected', _COL_X[3], y + 6.5);
//   }

// In Strengths & Priority Improvements page (PDF page 3), add a distinct
// "Execution Notes" section after Priority Improvements when gaps exist:
function renderExecutionGapSection(doc, summaryData, y, MARGIN, CONTENT_W) {
    const gapItems = [];
    (summaryData || []).forEach(pillar => {
        (pillar.criteriaScores || []).forEach(crit => {
            if (crit.executionGap) {
                gapItems.push({ pillar: pillar.pillar, criterion: crit.label });
            }
        });
    });

    if (gapItems.length === 0) return y;

    // Section header
    doc.setFont('helvetica', 'bold'); doc.setFontSize(9.5);
    doc.setTextColor(130, 90, 0);  // amber heading — informational tone
    doc.text('Execution Notes', MARGIN, y);
    y += 5;

    doc.setFont('helvetica', 'normal'); doc.setFontSize(8);
    doc.setTextColor(80, 55, 0);
    const _noteIntro = doc.splitTextToSize(
        'The following criteria have governance documentation in place, but no artefacts ' +
        'demonstrating active practice were found in publicly available sources. ' +
        'This does not indicate that the practices are absent — it indicates that ' +
        'public evidence of execution has not been detected.',
        CONTENT_W
    );
    doc.text(_noteIntro, MARGIN, y);
    y += _noteIntro.length * 4 + 4;

    gapItems.slice(0, 8).forEach(item => {
        doc.setFont('helvetica', 'normal'); doc.setFontSize(8);
        doc.setTextColor(80, 55, 0);
        doc.text('› ' + item.pillar + ' — ' + item.criterion, MARGIN + 2, y);
        y += 5;
    });

    return y + 4;
}


// ══════════════════════════════════════════════════════════════
// SECTION 8: Supabase columns
// ══════════════════════════════════════════════════════════════

const EXECUTION_SQL = `
ALTER TABLE hai_analysis_logs
    ADD COLUMN IF NOT EXISTS execution_gap_count      INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS verified_execution_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS execution_score_avg      NUMERIC(4,3) DEFAULT NULL;

CREATE OR REPLACE VIEW v_execution_gaps_by_industry AS
SELECT
    industry,
    ROUND(AVG(execution_gap_count)::numeric, 1)       AS avg_execution_gaps,
    ROUND(AVG(verified_execution_count)::numeric, 1)  AS avg_verified_executions,
    ROUND(AVG(final_score)::numeric, 1)               AS avg_score,
    COUNT(*)                                           AS assessment_count
FROM hai_analysis_logs
WHERE execution_gap_count IS NOT NULL
GROUP BY industry
ORDER BY avg_execution_gaps DESC;
`;


module.exports = {
    EXECUTION_KEYWORDS,
    EXECUTION_CATEGORY_WEIGHTS,
    OPENAI_EXECUTION_INSTRUCTION,
    computeExecutionScore,
    annotateWithExecutionScore,
    upgradeRoleByExecution,
    detectExecutionGap,
    scanExecutionGaps,
    executionBonus,
    renderExecutionGapSection,
    EXECUTION_SQL
};
