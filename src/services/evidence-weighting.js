// ============================================================
// FIX 8 — EVIDENCE WEIGHTING: SOURCE TIER × MATERIALITY × EVIDENCE TYPE
// FILES: src/services/supplementary-evidence.js  (backend)
//        bundle.js  (frontend scoring, near STAGE_WEIGHTS + updateDashboard)
//
// HAI DESIGN PRINCIPLE:
//   Legal and regulatory evidence is treated as highly material
//   because it represents verified, consequential governance signals.
//   But the index remains a human-alignment index — not a compliance
//   risk score. Safety criteria carry the highest regulatory weight,
//   but Trust, Purpose, Impact, and Transparency remain substantive
//   pillars with genuine materiality of their own.
//
//   The materiality weights below are calibrated so that:
//   - No single pillar dominates (safety_total ≈ trust_total)
//   - Impact criteria score meaningfully — human outcomes are central
//   - Purpose criteria are not penalised for lower regulatory coverage
//   - The system rewards demonstrated governance across all six pillars
//
// WHAT CHANGES:
//   The Phase 4 formula:
//     confidence = tierWeight × specificityMultiplier × 30
//   treats all 20 criteria equally and ignores evidence type.
//
//   The Phase 6 formula:
//     contribution = tierWeight × roleMultiplier × evidenceTypeMult × materiality × 30
//   gives proportionally more weight to:
//     - higher-consequence criteria (materiality)
//     - independently verified evidence (evidence type)
//
//   The effect is deliberately modest within any single pillar:
//   ~10% differential between the highest and lowest materiality criteria.
//   This preserves pillar balance while producing better discrimination
//   when evidence exists for some criteria and not others.
// ============================================================


// ══════════════════════════════════════════════════════════════
// SECTION 1: CRITERION MATERIALITY WEIGHTS
// Add near top of supplementary-evidence.js AND bundle.js,
// immediately before STAGE_WEIGHTS (~line 954 in bundle.js).
//
// Rationale for weighting approach:
//   1.0 = baseline  |  >1.0 = higher consequence if absent
//   <1.0 = genuinely important but lower regulatory enforcement currently
//
// Pillar totals are kept close to each other (range 3.5–4.6) to
// preserve the pillar balance defined in STAGE_WEIGHTS.
// ══════════════════════════════════════════════════════════════

const CRITERION_MATERIALITY = {
    // ── TRUST (sum: 4.4) ────────────────────────────────────────────────
    // Trust is central to HAI identity. User confidence and absence of
    // manipulation are the highest-consequence human-facing criteria.
    'trust_user_confidence':          1.2,  // Right to understand AI interactions; EU AI Act Art.13
    'trust_consistency_of_behavior':  1.0,  // System reliability; detectable post-deployment
    'trust_ethical_intent':           1.1,  // Governance culture; foundational to all other pillars
    'trust_absence_of_manipulation':  1.1,  // Dark patterns cause direct harm; FTC/ICO enforcement focus

    // ── ACCOUNTABILITY (sum: 3.8) ──────────────────────────────────────
    // Named ownership and corrective action are legally required
    // under EU AI Act Art.16 and ISO 42001 §5.3.
    'accountability_ownership_of_outcomes':    1.4,  // Legally required named owner; highest regulatory exposure
    'accountability_corrective_action':        1.1,  // Incident response; absence = liability
    'accountability_governance_and_oversight': 1.3,  // Board-level AI governance; ISO 42001 §6

    // ── PURPOSE (sum: 3.1) ────────────────────────────────────────────
    // Purpose pillars are strategic and human-centred. Lower regulatory
    // enforcement currently does not make them less important to HAI
    // certification — they represent the "why" of human alignment.
    'purpose_mission_clarity':         0.9,  // Strategic alignment; lower regulatory consequence
    'purpose_human_centered_intent':   1.1,  // Core HAI criterion; AI that serves human need
    'purpose_alignment_words_actions': 1.1,  // Intent vs practice gap; greenwashing risk

    // ── SAFETY (sum: 4.0) ────────────────────────────────────────────
    // Safety has the highest individual criterion weights due to legal
    // requirements, but the pillar total is kept near Trust to preserve
    // the HAI balance between safety and alignment.
    'safety_risk_mitigation':              1.4,  // Legally required: EU AI Act Art.9; NIST RMF Gov.1
    'safety_user_protection_mechanisms':   1.3,  // Active user safeguards; product liability surface
    'safety_long_term_societal_safety':    1.3,  // Systemic risk; essential for mature deployments

    // ── TRANSPARENCY (sum: 3.5) ────────────────────────────────────────
    'transparency_explainability':        1.2,  // Right to explanation; EU AI Act Art.13
    'transparency_data_disclosure':       1.2,  // GDPR/CCPA compliance surface
    'transparency_communication_honesty': 1.1,  // Disclosure quality; harder to audit externally

    // ── IMPACT (sum: 4.0) ─────────────────────────────────────────────
    // Impact criteria are central to HAI's human-alignment identity.
    // Measurable positive outcomes are what distinguishes genuine
    // alignment from compliance box-ticking. Impact is not deprioritised.
    'impact_positive_human_outcomes':  1.3,  // Core HAI requirement; must be demonstrable
    'impact_shared_human_benefit':     1.0,  // Broad societal benefit; integral to HAI purpose
    'impact_measurability_of_impact':  1.2,  // Without metrics, impact claims are unverifiable
    'impact_durability_of_impact':     0.8   // Long-term lens; genuine but least immediate consequence
};

// Pillar totals for transparency (useful when calibrating):
//   trust: 4.4 | accountability: 3.8 | purpose: 3.1
//   safety: 4.0 | transparency: 3.5 | impact: 4.0 + durability 0.8 = 4.3 (4 criteria)
// Range is intentionally narrow — the index rewards balance.

const DEFAULT_MATERIALITY = 1.0;

function getMaterialityWeight(criterionId) {
    return CRITERION_MATERIALITY[criterionId] || DEFAULT_MATERIALITY;
}


// ══════════════════════════════════════════════════════════════
// SECTION 2: EVIDENCE TYPE MULTIPLIERS
// Unchanged from the Phase 6 spec. Rewards independently
// verified evidence over self-published policy statements.
// ══════════════════════════════════════════════════════════════

const ROLE_MULTIPLIER = {
    'justifies':   1.0,
    'supports':    0.5,
    'contradicts': 0.0   // handled by FIX-9 override logic
};

const EVIDENCE_TYPE_MULTIPLIER = {
    'governance':  0.7,   // policy, statement — intent without execution proof
    'operational': 1.0,   // process, control, metric — execution evidence (baseline)
    'external':    1.3    // independent audit, ISO certification, regulatory filing
};

function getEvidenceTypeMultiplier(evidenceType) {
    return EVIDENCE_TYPE_MULTIPLIER[evidenceType] || 1.0;
}


// ══════════════════════════════════════════════════════════════
// SECTION 3: REVISED CONFIDENCE CONTRIBUTION FORMULA
// File: src/services/supplementary-evidence.js
//
// Calibration: HIGH-trust + operational + justifies + materiality 1.0
//   = 1.0 × 1.0 × 1.0 × 1.0 × 30 = 30 pts  (Phase 4 baseline preserved)
// ══════════════════════════════════════════════════════════════

const BASE_CONTRIBUTION = 30;

function computeWeightedContribution(evidenceItem, criterionId) {
    if (evidenceItem.role === 'contradicts') return 0;

    const tierWeight   = evidenceItem.tierWeight || 0.25;
    const roleMult     = ROLE_MULTIPLIER[evidenceItem.role] || 0.5;
    const etMult       = getEvidenceTypeMultiplier(evidenceItem.evidenceType);
    const materiality  = getMaterialityWeight(criterionId);

    return Math.round(tierWeight * roleMult * etMult * materiality * BASE_CONTRIBUTION * 10) / 10;
}


// ══════════════════════════════════════════════════════════════
// SECTION 4: computeCriterionConfidence()
// File: src/services/supplementary-evidence.js
//
// REPLACES the existing function of the same name.
// Also integrates the execution bonus from FIX-12.
// ══════════════════════════════════════════════════════════════

function computeCriterionConfidence(criterionId, evidenceItems, executionLevel) {
    if (!evidenceItems || evidenceItems.length === 0) return 0;

    let totalContribution = 0;
    evidenceItems.forEach(item => {
        totalContribution += computeWeightedContribution(item, criterionId);
    });

    // Corroboration bonus: multiple independent sources increase credibility
    const uniqueSources = new Set(evidenceItems.map(i => i.source)).size;
    let corroborationBonus = 0;
    if (uniqueSources >= 3)      corroborationBonus = 15;
    else if (uniqueSources >= 2) corroborationBonus = 8;

    const mat         = getMaterialityWeight(criterionId);
    const scaledBonus = Math.round(corroborationBonus * mat);

    // Execution bonus from FIX-12 (import executionBonus separately)
    // executionBonus: verified=+20, partial=+10, asserted=0, none=-5
    const _execBonus = executionBonusLookup(executionLevel);

    return Math.min(100, Math.max(0, Math.round(totalContribution + scaledBonus + _execBonus)));
}

// Inline lookup so this file can stand alone (FIX-12 also exports executionBonus)
function executionBonusLookup(executionLevel) {
    const table = { verified: 20, partial: 10, asserted: 0, none: -5 };
    return table[executionLevel] || 0;
}


// ══════════════════════════════════════════════════════════════
// SECTION 5: FRONTEND MATERIALITY SCORING (bundle.js)
//
// Two surgical changes in updateDashboard().
// Identical changes needed in the pdfSummaryContent loop.
// ══════════════════════════════════════════════════════════════

// ADD to bundle.js immediately before STAGE_WEIGHTS (~line 954):
//
//   const CRITERION_MATERIALITY = { ... };   // paste Section 1 above
//   const DEFAULT_MATERIALITY = 1.0;
//   function getMaterialityWeight(criterionId) {
//       return CRITERION_MATERIALITY[criterionId] || DEFAULT_MATERIALITY;
//   }
//
// ── Change 1: criterion ratio loop (~line 1725) ────────────────────────
// FIND inside p.criteria.forEach(c => { ... }):
//   const ratio = (lvl - 1) / 4;
//   pRatios += ratio;
//
// REPLACE WITH:
//   const mat   = getMaterialityWeight(c.id);
//   const ratio = ((lvl - 1) / 4) * mat;
//   pRatios += ratio;
//
// ── Change 2: avgRatio normalisation (~line 1733) ─────────────────────
// FIND:
//   const avgRatio = pRatios / p.criteria.length;
//
// REPLACE WITH:
//   const totalMat = p.criteria.reduce((sum, c) => sum + getMaterialityWeight(c.id), 0);
//   const avgRatio = pRatios / totalMat;
//
// ── Apply identical change in pdfSummaryContent loop (~line 2042) ──────
//   Same two-line replacement. avgRatio there feeds pillarScore displayed in PDF.


// ══════════════════════════════════════════════════════════════
// SECTION 6: MATERIALITY INDICATOR IN PDF CRITERION GRID
// Extends FIX-4's printPillarBlock. Adds a small indicator
// showing whether a criterion carries higher or standard consequence.
// ══════════════════════════════════════════════════════════════

function renderCriterionLevelBadge(doc, criterionId, lvl, x, y) {
    const mat = getMaterialityWeight(criterionId);

    const _lvlColor = lvl >= 4 ? [11, 114, 57]
                    : lvl >= 3 ? [30, 100, 200]
                    : lvl >= 2 ? [180, 120, 0]
                    : [196, 30, 30];

    doc.setFont('helvetica', 'bold'); doc.setFontSize(7.5);
    doc.setTextColor(_lvlColor[0], _lvlColor[1], _lvlColor[2]);
    doc.text('L' + lvl + '/5', x, y);

    // Materiality indicator: ▲ = higher consequence  ▽ = lower consequence
    // Only shown at the extremes — standard criteria get no indicator
    if (mat >= 1.3) {
        doc.setFont('helvetica', 'normal'); doc.setFontSize(6);
        doc.setTextColor(180, 50, 50);
        doc.text('▲', x + 13, y);
    } else if (mat < 0.9) {
        doc.setFont('helvetica', 'normal'); doc.setFontSize(6);
        doc.setTextColor(140, 140, 140);
        doc.text('▽', x + 13, y);
    }
    // mat 0.9–1.29: no indicator — standard consequence, no visual noise
}

// Add legend below criterion grid header:
// '▲ Higher governance consequence   ▽ Lower consequence'
// Only renders if any criteria in the pillar have extreme materiality.


module.exports = {
    CRITERION_MATERIALITY,
    EVIDENCE_TYPE_MULTIPLIER,
    ROLE_MULTIPLIER,
    getMaterialityWeight,
    getEvidenceTypeMultiplier,
    computeWeightedContribution,
    computeCriterionConfidence,
    renderCriterionLevelBadge,
    BASE_CONTRIBUTION
};
