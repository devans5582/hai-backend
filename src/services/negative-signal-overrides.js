// ============================================================
// FIX 9 — NEGATIVE SIGNAL OVERRIDES
// FILES: src/services/supplementary-evidence.js  (backend)
//        src/routes/evaluate.js                  (backend integration)
//        bundle.js                               (frontend scoring + PDF)
//
// DESIGN PRINCIPLES:
//   Negative signals flag certification risk. They do not make
//   accusations. The system has detected publicly available
//   information that raises a governance question — it does not
//   adjudicate the matter.
//
//   Language in all user-facing output must:
//     - Describe what was detected, not what it proves
//     - State the impact on this assessment clearly
//     - Recommend human review, not deliver a verdict
//     - Never name a specific regulatory body as having acted
//       unless the source is a verified regulatory filing (EDGAR/GOVINFO)
//
//   Override severity determines scoring impact, not accusation level.
//   The PDF and UI surface a "Certification Risk Flag" — never
//   language that asserts wrongdoing.
//
// WHAT THIS REPLACES:
//   FIX-7 introduced a 'contradicts' role that caps criterion at level 2.
//   A cap only prevents future growth. This fix adds active level reduction
//   when the negative signal is significant enough to invalidate
//   previously earned evidence.
//
//   The distinction: a cap says "don't go higher."
//   An override says "the current level is no longer supportable."
// ============================================================


// ══════════════════════════════════════════════════════════════
// SECTION 1: OVERRIDE SEVERITY TIERS
// Four tiers. Severity determines score impact, not accusation severity.
// ══════════════════════════════════════════════════════════════

const OVERRIDE_SEVERITY = {
    FORCE_LEVEL_1:    'force_level_1',   // Level set to 1 — evidence no longer supportable
    REDUCE_2_STEPS:   'reduce_2_steps',  // Level reduced by 2 (min 1)
    REDUCE_1_STEP:    'reduce_1_step',   // Level reduced by 1 (min 1)
    CONFIDENCE_FLOOR: 'confidence_floor' // Level unchanged; confidence capped at 20%
};


// ══════════════════════════════════════════════════════════════
// SECTION 2: SEVERITY MAP
// Maps source × text signal → severity tier + user-facing description.
//
// Description language rules (enforced here):
//   - Describe the detected signal, not a conclusion about the company
//   - Use "reported", "detected", "identified in public sources"
//   - Never: "proved", "confirmed wrongdoing", "guilty of", "violated"
//   - For EDGAR/GOVINFO sources: slightly stronger language is acceptable
//     because these are verified regulatory filings, not news reports
// ══════════════════════════════════════════════════════════════

const NEGATIVE_SIGNAL_SEVERITY_MAP = [

    // ── Tier 1: Verified regulatory/legal record ───────────────────────
    // Source is a verified regulatory filing (EDGAR, GOVINFO).
    // These are documents filed with or issued by authorities, not reports about them.
    {
        sourcePattern:   /^(EDGAR|GOVINFO)$/,
        textPatterns:    [
            'enforcement action', 'consent decree', 'regulatory order',
            'court order', 'injunction', 'civil penalty', 'settlement order',
            'cease and desist', 'gdpr fine', 'ico penalty', 'ftc order'
        ],
        affectedPillars: ['trust', 'accountability', 'safety'],
        severity:        OVERRIDE_SEVERITY.FORCE_LEVEL_1,
        // Description seen by human reviewer — factual, not accusatory
        userFacingDescription: 'A regulatory filing or order was identified in verified public records ' +
            'for this entity. This assessment cannot support current governance levels for the ' +
            'affected criteria while this filing is active. Human review is required.'
    },

    // ── Tier 2: Reported active legal proceeding ──────────────────────
    // Multiple source types. Language must reflect that this is reported,
    // not confirmed by a regulatory body.
    {
        sourcePattern:   /^(EDGAR|GOVINFO|NEWS_NEGATIVE)$/,
        textPatterns:    [
            'under investigation', 'regulatory inquiry', 'class action',
            'lawsuit filed', 'sec investigation', 'doj inquiry',
            'formal complaint filed', 'regulatory probe'
        ],
        affectedPillars: ['trust', 'accountability', 'transparency'],
        severity:        OVERRIDE_SEVERITY.REDUCE_2_STEPS,
        userFacingDescription: 'An active legal or regulatory proceeding involving this entity ' +
            'was detected in public sources. This may affect the reliability of current ' +
            'governance evidence. Human review is recommended before using this score.'
    },

    // ── Tier 3: Reported AI harm or safety incident ───────────────────
    {
        sourcePattern:   /^(NEWS_NEGATIVE|EDGAR|ACADEMIC)$/,
        textPatterns:    [
            'ai safety incident', 'ai harm reported', 'algorithmic harm',
            'ai bias documented', 'ai failure', 'data breach confirmed',
            'ai system recall', 'ai deployment halted'
        ],
        affectedPillars: ['safety', 'trust', 'impact'],
        severity:        OVERRIDE_SEVERITY.REDUCE_2_STEPS,
        userFacingDescription: 'A reported safety or harm event involving AI systems ' +
            'associated with this entity was detected in public sources. ' +
            'The affected criteria reflect reduced confidence pending review.'
    },

    // ── Tier 4: Reported policy contradiction ─────────────────────────
    {
        sourcePattern:   /^(NEWS_NEGATIVE|NEWS|ACADEMIC)$/,
        textPatterns:    [
            'contradicts stated policy', 'policy not followed',
            'claims disputed', 'misleading ai claims',
            'ai transparency gap reported', 'broken commitment'
        ],
        affectedPillars: ['transparency', 'trust', 'purpose'],
        severity:        OVERRIDE_SEVERITY.REDUCE_1_STEP,
        userFacingDescription: 'Publicly available sources report a gap between stated governance ' +
            'commitments and observed practice. One level has been deducted from affected criteria ' +
            'pending review. This does not represent a finding of wrongdoing.'
    },

    // ── Tier 5: Unverified criticism or concern (news/low-trust only) ──
    // Confidence floor only — level is not reduced based on unverified reporting.
    {
        sourcePattern:   /^(NEWS|WAYBACK|GITHUB)$/,
        textPatterns:    [
            'criticism', 'concerns raised', 'critics say',
            'questioned', 'lack of transparency', 'pressure to improve'
        ],
        affectedPillars: ['trust', 'transparency'],
        severity:        OVERRIDE_SEVERITY.CONFIDENCE_FLOOR,
        userFacingDescription: 'Reported concerns about governance practices were detected in ' +
            'lower-confidence sources. Criterion confidence has been moderated. ' +
            'Criterion levels are unchanged. No score reduction has been applied.'
    },
];


// ══════════════════════════════════════════════════════════════
// SECTION 3: classifyNegativeSignal(item)
// Returns a severity classification for a negative evidence item.
// ══════════════════════════════════════════════════════════════

function classifyNegativeSignal(item) {
    if (!item || (item.role !== 'contradicts' && !item.isNegativeSignal)) return null;

    const _text   = (item.text || '').toLowerCase();
    const _source = (item.source || '').toUpperCase();

    for (const rule of NEGATIVE_SIGNAL_SEVERITY_MAP) {
        const sourceMatch = rule.sourcePattern.test(_source);
        const textMatch   = rule.textPatterns.some(p => _text.includes(p.toLowerCase()));

        if (sourceMatch && textMatch) {
            return {
                severity:             rule.severity,
                affectedPillars:      rule.affectedPillars,
                userFacingDescription: rule.userFacingDescription,
                matchedPattern:       rule.textPatterns.find(p => _text.includes(p.toLowerCase())),
                sourceType:           _source,
                originalItem:         item
            };
        }
    }

    // Default: any unclassified negative signal from a medium/high-trust source
    // reduces by 1 step. Low-trust unclassified signals → confidence floor only.
    const isHighTrustSource = /^(EDGAR|GOVINFO|ISO_42001|NIST_RMF)$/.test(_source);
    const isMediumTrustSource = /^(NEWS_NEGATIVE|ACADEMIC|OECD)$/.test(_source);

    return {
        severity:             isHighTrustSource  ? OVERRIDE_SEVERITY.REDUCE_1_STEP
                            : isMediumTrustSource ? OVERRIDE_SEVERITY.REDUCE_1_STEP
                            : OVERRIDE_SEVERITY.CONFIDENCE_FLOOR,
        affectedPillars:      item.relevantPillars || ['trust'],
        userFacingDescription: 'A governance risk signal was detected in public sources. ' +
            'The affected criteria reflect reduced confidence. Human review is recommended.',
        matchedPattern:       null,
        sourceType:           _source,
        originalItem:         item
    };
}


// ══════════════════════════════════════════════════════════════
// SECTION 4: applyNegativeOverrides()
// File: src/services/supplementary-evidence.js
//
// Runs AFTER maturity gating, BEFORE calibration uplift.
// Returns modified assessmentState plus a full audit log.
// Only reduces scores — never increases them.
// ══════════════════════════════════════════════════════════════

function applyNegativeOverrides(assessmentState, allEvidenceItems, rubricDef) {
    const overrideLog = [];

    const negativeSignals = allEvidenceItems
        .filter(item => item.role === 'contradicts' || item.isNegativeSignal)
        .map(item => classifyNegativeSignal(item))
        .filter(Boolean);

    if (negativeSignals.length === 0) {
        return { assessmentState, overrideLog, hasOverrides: false, worstSeverity: null };
    }

    // Deep copy — overrides must never mutate the original state object
    const updatedState = JSON.parse(JSON.stringify(assessmentState));

    negativeSignals.forEach(signal => {
        const affectedCriteria = rubricDef.pillars
            .filter(pillar => signal.affectedPillars.includes(pillar.id))
            .flatMap(pillar => pillar.criteria);

        affectedCriteria.forEach(criterion => {
            const critState    = updatedState[criterion.id];
            if (!critState) return;

            const currentLevel = parseInt(critState.level, 10) || 1;

            switch (signal.severity) {
                case OVERRIDE_SEVERITY.FORCE_LEVEL_1: {
                    if (currentLevel > 1) {
                        updatedState[criterion.id] = {
                            ...critState,
                            level:            1,
                            overrideApplied:  signal.severity,
                            preOverrideLevel: currentLevel,
                            overrideReason:   signal.userFacingDescription
                        };
                        overrideLog.push({
                            criterionId:     criterion.id,
                            criterionLabel:  criterion.label,
                            from:            currentLevel,
                            to:              1,
                            severity:        signal.severity,
                            sourceType:      signal.sourceType,
                            // Store only the user-facing description in the log — no raw text
                            description:     signal.userFacingDescription
                        });
                    }
                    break;
                }

                case OVERRIDE_SEVERITY.REDUCE_2_STEPS: {
                    const newLevel = Math.max(1, currentLevel - 2);
                    if (newLevel < currentLevel) {
                        updatedState[criterion.id] = {
                            ...critState,
                            level:            newLevel,
                            overrideApplied:  signal.severity,
                            preOverrideLevel: currentLevel,
                            overrideReason:   signal.userFacingDescription
                        };
                        overrideLog.push({
                            criterionId:    criterion.id,
                            criterionLabel: criterion.label,
                            from:           currentLevel,
                            to:             newLevel,
                            severity:       signal.severity,
                            sourceType:     signal.sourceType,
                            description:    signal.userFacingDescription
                        });
                    }
                    break;
                }

                case OVERRIDE_SEVERITY.REDUCE_1_STEP: {
                    const newLevel = Math.max(1, currentLevel - 1);
                    if (newLevel < currentLevel) {
                        updatedState[criterion.id] = {
                            ...critState,
                            level:            newLevel,
                            overrideApplied:  signal.severity,
                            preOverrideLevel: currentLevel,
                            overrideReason:   signal.userFacingDescription
                        };
                        overrideLog.push({
                            criterionId:    criterion.id,
                            criterionLabel: criterion.label,
                            from:           currentLevel,
                            to:             newLevel,
                            severity:       signal.severity,
                            sourceType:     signal.sourceType,
                            description:    signal.userFacingDescription
                        });
                    }
                    break;
                }

                case OVERRIDE_SEVERITY.CONFIDENCE_FLOOR: {
                    // Level unchanged — only confidence is capped
                    updatedState[criterion.id] = {
                        ...critState,
                        confidenceCeiling: 20,
                        overrideApplied:   signal.severity,
                        overrideReason:    signal.userFacingDescription
                    };
                    overrideLog.push({
                        criterionId:    criterion.id,
                        criterionLabel: criterion.label,
                        from:           currentLevel,
                        to:             currentLevel,   // level unchanged
                        severity:       signal.severity,
                        sourceType:     signal.sourceType,
                        description:    signal.userFacingDescription
                    });
                    break;
                }
            }
        });
    });

    // Determine worst severity across all applied overrides
    const severityRank = [
        OVERRIDE_SEVERITY.CONFIDENCE_FLOOR,
        OVERRIDE_SEVERITY.REDUCE_1_STEP,
        OVERRIDE_SEVERITY.REDUCE_2_STEPS,
        OVERRIDE_SEVERITY.FORCE_LEVEL_1
    ];
    const worstSeverity = overrideLog.length === 0 ? null :
        severityRank.reduce((worst, tier) =>
            overrideLog.some(o => o.severity === tier) ? tier : worst
        , null);

    return {
        assessmentState: updatedState,
        overrideLog,
        hasOverrides:    overrideLog.length > 0,
        worstSeverity
    };
}


// ══════════════════════════════════════════════════════════════
// SECTION 5: CERTIFICATION RISK FLAG
// Replaces the previously proposed "Certification Hold" label.
//
// "Certification Hold" implied a formal process. The correct
// framing is a risk flag that triggers human review — it does
// not block the score from being used, but it annotates it clearly.
//
// FIND in bundle.js (~line 1907), after certLabel is assigned:
// ADD the block below.
// ══════════════════════════════════════════════════════════════

/*
    // ── Certification risk flag (FIX-9) ───────────────────────────────────
    const _overrideResult = window.currentSupplementary &&
                            window.currentSupplementary._negativeOverrideResult;
    const _worstSeverity  = _overrideResult && _overrideResult.worstSeverity;
    window.currentOverrideLog = (_overrideResult && _overrideResult.overrideLog) || [];

    if (_worstSeverity === 'force_level_1') {
        // Flag alongside cert status — do not replace it entirely
        // (the score itself reflects the override; the label informs the reader)
        window.currentCertRiskFlag = {
            level:   'high',
            label:   'Certification Risk Flag — Human Review Required',
            message: 'Public records identified during this assessment may affect certification ' +
                     'readiness. This score reflects all available evidence. A human review is ' +
                     'required before this assessment is used for certification purposes.',
        };
    } else if (_worstSeverity === 'reduce_2_steps') {
        window.currentCertRiskFlag = {
            level:   'moderate',
            label:   'Governance Risk Signal Detected',
            message: 'One or more governance risk signals were identified in public sources. ' +
                     'Affected criteria have been adjusted. Review the Evidence Appendix for details.',
        };
    } else if (_worstSeverity) {
        window.currentCertRiskFlag = {
            level:   'informational',
            label:   'Assessment Note',
            message: 'Governance signals requiring monitoring were detected in public sources. ' +
                     'Criterion confidence has been moderated. See the Evidence Appendix.',
        };
    }
*/


// ══════════════════════════════════════════════════════════════
// SECTION 6: PDF — RISK FLAG BANNER + OVERRIDE AUDIT TRAIL
// File: bundle.js
//
// renderCertRiskFlagBlock() — replaces the previously proposed
// renderCertificationHoldBlock(). Careful language throughout.
// ══════════════════════════════════════════════════════════════

function renderCertRiskFlagBlock(doc, certRiskFlag, overrideLog, y, MARGIN, CONTENT_W, BRAND_RED) {
    if (!certRiskFlag) return y;

    const _colors = {
        high:          { bg: [255, 232, 232], border: BRAND_RED,        text: [140, 30, 30]  },
        moderate:      { bg: [255, 246, 220], border: [180, 120,   0],  text: [120, 80,  0]  },
        informational: { bg: [240, 246, 255], border: [60,  100, 180],  text: [40,  70, 140] }
    };
    const _c = _colors[certRiskFlag.level] || _colors.informational;

    // Banner
    doc.setFillColor(_c.bg[0], _c.bg[1], _c.bg[2]);
    doc.setDrawColor(_c.border[0], _c.border[1], _c.border[2]);
    doc.setLineWidth(0.5);
    doc.roundedRect(MARGIN, y, CONTENT_W, 8, 1.5, 1.5, 'FD');
    doc.setFont('helvetica', 'bold'); doc.setFontSize(9);
    doc.setTextColor(_c.text[0], _c.text[1], _c.text[2]);
    doc.text(certRiskFlag.label, MARGIN + 3, y + 5.5);
    y += 10;

    // Message
    const _msgLines = doc.splitTextToSize(certRiskFlag.message, CONTENT_W - 4);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(8);
    doc.setTextColor(_c.text[0], _c.text[1], _c.text[2]);
    doc.text(_msgLines, MARGIN + 2, y);
    y += _msgLines.length * 4 + 5;

    return y;
}

function renderOverrideAuditTrail(doc, overrideLog, y, MARGIN, CONTENT_W) {
    if (!overrideLog || overrideLog.length === 0) return y;

    doc.setFont('helvetica', 'bold'); doc.setFontSize(9);
    doc.setTextColor(60, 60, 60);
    doc.text('Assessment Adjustments Log', MARGIN, y);
    y += 6;

    // Explanatory note — sets expectations before the log entries
    const _note = doc.splitTextToSize(
        'The following adjustments were applied during scoring based on signals detected in ' +
        'publicly available sources. Each entry describes the criterion affected, the adjustment ' +
        'made, and the reason. This log is provided for transparency.',
        CONTENT_W
    );
    doc.setFont('helvetica', 'italic'); doc.setFontSize(7.5);
    doc.setTextColor(80, 80, 80);
    doc.text(_note, MARGIN, y);
    y += _note.length * 4 + 4;

    overrideLog.forEach((ov, idx) => {
        const _isEven = idx % 2 === 0;
        const _bg     = _isEven ? [252, 248, 248] : [248, 248, 248];

        doc.setFillColor(_bg[0], _bg[1], _bg[2]);
        doc.rect(MARGIN, y, CONTENT_W, 9, 'F');

        // Criterion label + adjustment
        doc.setFont('helvetica', 'bold'); doc.setFontSize(7.5);
        doc.setTextColor(50, 50, 50);
        doc.text(ov.criterionLabel || ov.criterionId, MARGIN + 2, y + 4);

        // Adjustment: level change or confidence floor
        const _adjText = ov.from !== ov.to
            ? 'Level adjusted: L' + ov.from + ' → L' + ov.to
            : 'Confidence moderated (level unchanged)';
        doc.setFont('helvetica', 'normal'); doc.setFontSize(7);
        doc.setTextColor(100, 50, 50);
        doc.text(_adjText, MARGIN + 90, y + 4);

        // Source type — shows what kind of source triggered this
        doc.setFont('helvetica', 'italic'); doc.setFontSize(6.5);
        doc.setTextColor(120, 120, 120);
        doc.text('Source: ' + (ov.sourceType || 'Public record'), MARGIN + 148, y + 4);

        // Description on second line
        const _descLines = doc.splitTextToSize(ov.description, CONTENT_W - 4);
        doc.setFont('helvetica', 'normal'); doc.setFontSize(6.5);
        doc.setTextColor(90, 70, 70);
        doc.text(_descLines[0], MARGIN + 2, y + 7.5);  // first line only in row
        y += 10;
    });

    return y + 4;
}


// ══════════════════════════════════════════════════════════════
// SECTION 7: FRONTEND OVERRIDE APPLICATION (bundle.js)
// WHERE: After maturity gating (~line 1810), BEFORE calibration.
// Paste this comment block into updateDashboard() as Step 2b.
// ══════════════════════════════════════════════════════════════

/*
    // ── Step 2b: Apply negative overrides (FIX-9) ──────────────────────────
    // Backend computes override instructions and returns them in
    // supplementary_signals.impact.negativeOverrides.
    // Frontend applies them here so the score reflects them.
    // Overrides can ONLY reduce levels — never increase them.

    const _overrides = _sup && _sup.impact && _sup.impact.negativeOverrides;
    if (_overrides && _overrides.length > 0) {
        _overrides.forEach(function(ov) {
            const critState = assessmentState[ov.criterionId];
            if (!critState) return;

            const currentLevel = parseInt(critState.level, 10) || 1;

            if (ov.severity === 'force_level_1' && currentLevel > 1) {
                assessmentState[ov.criterionId] = Object.assign({}, critState, {
                    level: 1,
                    overrideApplied: ov.severity,
                    preOverrideLevel: currentLevel
                });
            } else if (ov.severity === 'reduce_2_steps') {
                const newLvl = Math.max(1, currentLevel - 2);
                if (newLvl < currentLevel) {
                    assessmentState[ov.criterionId] = Object.assign({}, critState, {
                        level: newLvl,
                        overrideApplied: ov.severity,
                        preOverrideLevel: currentLevel
                    });
                }
            } else if (ov.severity === 'reduce_1_step') {
                const newLvl = Math.max(1, currentLevel - 1);
                if (newLvl < currentLevel) {
                    assessmentState[ov.criterionId] = Object.assign({}, critState, {
                        level: newLvl,
                        overrideApplied: ov.severity,
                        preOverrideLevel: currentLevel
                    });
                }
            } else if (ov.severity === 'confidence_floor') {
                assessmentState[ov.criterionId] = Object.assign({}, critState, {
                    confidenceCeiling: 20,
                    overrideApplied: ov.severity
                });
            }
        });

        // Store override result for PDF and UI rendering
        if (window.currentSupplementary) {
            window.currentSupplementary._negativeOverrideResult = {
                overrideLog:   _overrides,
                worstSeverity: _sup.impact.worstSeverity || null,
                hasOverrides:  true
            };
        }
        console.log('[HAI] Override adjustments applied: ' + _overrides.length + ' criteria affected');
    }
*/

module.exports = {
    OVERRIDE_SEVERITY,
    NEGATIVE_SIGNAL_SEVERITY_MAP,
    classifyNegativeSignal,
    applyNegativeOverrides,
    renderCertRiskFlagBlock,
    renderOverrideAuditTrail
};
