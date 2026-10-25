// ============================================================
// FIX 10 — TIME DECAY: EVIDENCE STALENESS + CERTIFICATION VALIDITY
// FILES: src/services/supplementary-evidence.js  (backend)
//        bundle.js                               (frontend UI + PDF)
//
// DESIGN PRINCIPLES:
//   Evidence from different sources becomes less reliable at different
//   rates. A news article is only current on its publication date.
//   An EDGAR filing is meaningful for roughly 18 months. A scrape of
//   a company's governance page may be current or may be stale within
//   weeks if the company updates it.
//
//   ACTIVE CERTIFICATIONS are a special case: when an ISO 42001 or
//   NIST RMF certification is active (not expired), it carries full
//   weight for its validity period and then decays after expiry.
//   This is meaningfully different from a policy document — a cert
//   has a defined validity date that anchors the time calculation.
//
//   When no date is available on an evidence item, the system uses a
//   conservative default (18 months) rather than assuming recency.
//   This is disclosed in the PDF output ("date not detected").
// ============================================================


// ══════════════════════════════════════════════════════════════
// SECTION 1: DECAY CURVES PER SOURCE
// half-life in months; floor = minimum multiplier after full decay
//
// noDecay flag is not used — all evidence decays eventually.
// Instead, active certifications use certValidUntil to anchor
// the decay start date (see Section 4 below).
// ══════════════════════════════════════════════════════════════

const DECAY_CURVES = {
    // Active certifications — decay starts from cert expiry, not detection date
    'ISO_42001':     { halfLifeMonths: 24,  floor: 0.6 },   // 3-year cert cycle typical
    'NIST_RMF':      { halfLifeMonths: 24,  floor: 0.55 },  // voluntary adoption; reviewed annually

    // Verified regulatory filings
    'EDGAR':         { halfLifeMonths: 18,  floor: 0.4 },   // annual filings expected
    'GOVINFO':       { halfLifeMonths: 24,  floor: 0.4 },   // policy documents updated less frequently

    // Institutional sources
    'OECD':          { halfLifeMonths: 30,  floor: 0.5 },   // institutional research is more durable
    'ACADEMIC':      { halfLifeMonths: 36,  floor: 0.5 },   // peer-reviewed; slower revision cycle

    // Website content — fast decay
    'WEBSITE':       { halfLifeMonths: 12,  floor: 0.3 },   // governance pages go stale quickly
    'WAYBACK':       { halfLifeMonths: 18,  floor: 0.25 },  // historical snapshot; best-effort

    // Code repositories
    'GITHUB':        { halfLifeMonths: 18,  floor: 0.2 },   // repos may become unmaintained

    // News — very fast decay; negative news decays slower (reputation risk lingers)
    'NEWS':          { halfLifeMonths: 3,   floor: 0.1 },
    'NEWS_NEGATIVE': { halfLifeMonths: 6,   floor: 0.4 },   // reputational signal persists longer

    // Default: applied when source is unrecognised
    'DEFAULT':       { halfLifeMonths: 18,  floor: 0.3 },
};

// Conservative default age when no date is detectable on the evidence item.
// 18 months: not catastrophically old, but not assumed current.
const DEFAULT_AGE_MONTHS_WHEN_UNDATED = 18;


// ══════════════════════════════════════════════════════════════
// SECTION 2: DATE PARSING UTILITIES
// parseEvidenceDate() tries multiple common date fields on an
// evidence item. Returns a Date object or null.
// ══════════════════════════════════════════════════════════════

function parseEvidenceDate(item) {
    const rawDate = item.dateIssued
                 || item.publishedDate
                 || item.date
                 || item.lastModified
                 || item.year
                 || null;

    if (!rawDate) return null;

    // Handle year-only strings (e.g. "2023") — treat as Jan 1 of that year
    if (/^\d{4}$/.test(String(rawDate))) {
        const d = new Date(parseInt(rawDate, 10), 0, 1);
        return isNaN(d.getTime()) ? null : d;
    }

    const parsed = new Date(rawDate);
    return isNaN(parsed.getTime()) ? null : parsed;
}

// Parse certification validity end date from evidence item
function parseCertValidUntil(item) {
    const rawDate = item.certValidUntil
                 || item.validUntil
                 || item.expiryDate
                 || item.certificationExpiry
                 || null;

    if (!rawDate) return null;
    const parsed = new Date(rawDate);
    return isNaN(parsed.getTime()) ? null : parsed;
}

function ageInMonths(date) {
    if (!date) return null;
    const now     = new Date();
    const diffMs  = now.getTime() - date.getTime();
    return diffMs / (1000 * 60 * 60 * 24 * 30.44);  // average month
}


// ══════════════════════════════════════════════════════════════
// SECTION 3: timeDecayMultiplier(item)
// Returns a 0.0–1.0 multiplier for a single evidence item.
// ══════════════════════════════════════════════════════════════

function timeDecayMultiplier(item) {
    const curve = DECAY_CURVES[item.source] || DECAY_CURVES['DEFAULT'];

    // ── Active certification case ──────────────────────────────────────
    // If the item has a certValidUntil date and it hasn't expired yet,
    // the evidence is fully current. Decay starts from the expiry date.
    if (item.source === 'ISO_42001' || item.source === 'NIST_RMF') {
        const validUntil = parseCertValidUntil(item);

        if (validUntil) {
            const now = new Date();

            if (validUntil > now) {
                // Cert is active — full weight
                return 1.0;
            } else {
                // Cert has expired — decay from expiry date
                const monthsSinceExpiry = ageInMonths(validUntil);
                return computeDecay(curve, monthsSinceExpiry);
            }
        }
        // No validity date found for cert source — fall through to standard path
    }

    // ── Standard decay: from evidence publication date ─────────────────
    const evidenceDate = parseEvidenceDate(item);
    const months = evidenceDate !== null
        ? ageInMonths(evidenceDate)
        : DEFAULT_AGE_MONTHS_WHEN_UNDATED;

    if (months <= 0) return 1.0;  // future-dated or today — treat as current

    return computeDecay(curve, months);
}

function computeDecay(curve, months) {
    // Exponential decay: weight = e^(-λt) where λ = ln(2) / halfLifeMonths
    const lambda  = Math.LN2 / curve.halfLifeMonths;
    const decayed = Math.exp(-lambda * months);
    return Math.max(curve.floor, Math.round(decayed * 1000) / 1000);
}


// ══════════════════════════════════════════════════════════════
// SECTION 4: annotateWithTimeDecay(items)
// Call after all evidence is assembled.
// Enriches every item with decay metadata.
// ══════════════════════════════════════════════════════════════

function annotateWithTimeDecay(items) {
    return items.map(item => {
        const decayMult    = timeDecayMultiplier(item);
        const evidDate     = parseEvidenceDate(item);
        const validUntil   = parseCertValidUntil(item);
        const months       = evidDate ? Math.round(ageInMonths(evidDate)) : null;
        const dateIsInferred = !evidDate;

        // isCertActive: true when a cert source has a future validity date
        const isCertActive = validUntil && validUntil > new Date();

        return {
            ...item,
            timeDecayMultiplier: decayMult,
            evidenceAgeMonths:   months,
            evidenceDate:        evidDate    ? evidDate.toISOString().slice(0, 10) : null,
            certValidUntilDate:  validUntil  ? validUntil.toISOString().slice(0, 10) : null,
            isCertActive:        isCertActive || false,
            dateIsInferred,
        };
    });
}


// ══════════════════════════════════════════════════════════════
// SECTION 5: INTEGRATE WITH computeWeightedContribution (FIX-8)
// File: src/services/supplementary-evidence.js
//
// In FIX-8's computeWeightedContribution(), multiply the base
// contribution by the time decay multiplier before returning.
//
// FIND in FIX-8 computeWeightedContribution():
//   return Math.round(tierWeight * roleMult * etMult * materiality * BASE_CONTRIBUTION * 10) / 10;
//
// REPLACE WITH:
//   const decay = item.timeDecayMultiplier !== undefined
//       ? item.timeDecayMultiplier
//       : timeDecayMultiplier(item);
//   return Math.round(tierWeight * roleMult * etMult * materiality * decay * BASE_CONTRIBUTION * 10) / 10;
//
// NOTE: annotateWithTimeDecay() should run before computeWeightedContribution
// so the decay value is pre-computed on the item, not recalculated per criterion.
// ══════════════════════════════════════════════════════════════


// ══════════════════════════════════════════════════════════════
// SECTION 6: OVERALL ASSESSMENT FRESHNESS SCORE
// Computed from the distribution of decay multipliers across
// all evidence items. Surfaced in UI and PDF alongside Evidence
// Quality and Evidence Coverage (FIX-3).
// ══════════════════════════════════════════════════════════════

function computeOverallFreshness(supplementary) {
    if (!supplementary || !supplementary.impact || !supplementary.impact.traceability) return null;

    const items = supplementary.impact.traceability.filter(
        item => item.timeDecayMultiplier !== undefined
    );
    if (items.length === 0) return null;

    const avg = items.reduce((sum, i) => sum + i.timeDecayMultiplier, 0) / items.length;
    return Math.round(avg * 100);
}

function getFreshnessLabel(freshnessPercent) {
    if (freshnessPercent === null || freshnessPercent === undefined) {
        return { label: 'Not assessed',  color: [150, 150, 150] };
    }
    if (freshnessPercent >= 80) return { label: 'Current',          color: [11,  114,  57] };
    if (freshnessPercent >= 60) return { label: 'Mostly current',   color: [30,  100, 200] };
    if (freshnessPercent >= 40) return { label: 'Mixed age',        color: [180, 120,   0] };
    return                             { label: 'Largely stale',    color: [160,  40,  40] };
}


// ══════════════════════════════════════════════════════════════
// SECTION 7: FRESHNESS CARD IN UI (bundle.js)
// Add a third evidence metric card alongside Quality and Coverage.
// Add to the results UI template in the evidence metrics row.
// ══════════════════════════════════════════════════════════════

// In updateDashboard(), after Evidence Quality and Coverage cards:
//
//   var _freshness      = computeOverallFreshness(window.currentSupplementary);
//   var _freshLabel     = getFreshnessLabel(_freshness);
//
//   var _freshnessCardHTML = `
//   <div style="background:var(--surface-2); padding:14px 20px; border-radius:10px;
//        text-align:center; border:1px solid var(--surface-border); min-width:130px;">
//     <div style="font-size:11px; font-weight:600; color:var(--text-2);
//          letter-spacing:0.06em; text-transform:uppercase; margin-bottom:6px;">
//       Evidence Freshness
//     </div>
//     <div style="font-size:36px; font-weight:700; color:var(--text-1); line-height:1;">
//       ${_freshness !== null ? _freshness + '<span style="font-size:18px; font-weight:400;">%</span>' : '—'}
//     </div>
//     <div style="margin-top:4px; font-size:11px; color:var(--text-2);">
//       ${_freshLabel.label}
//     </div>
//   </div>`;


// ══════════════════════════════════════════════════════════════
// SECTION 8: FRESHNESS LABELS IN PDF EVIDENCE APPENDIX (bundle.js)
// After each evidence item text, render freshness + date.
// Undated items show "Date not detected" — honest disclosure.
// ══════════════════════════════════════════════════════════════

function renderEvidenceFreshnessLabel(doc, item, x, y) {
    const _fresh    = getFreshnessLabel(
        item.timeDecayMultiplier !== undefined ? Math.round(item.timeDecayMultiplier * 100) : null
    );

    let _dateStr;
    if (item.isCertActive && item.certValidUntilDate) {
        _dateStr = 'Active certification — valid until ' + item.certValidUntilDate;
    } else if (item.evidenceDate) {
        const _ageStr = item.evidenceAgeMonths !== null
            ? ' (' + Math.round(item.evidenceAgeMonths) + ' months ago)'
            : '';
        _dateStr = item.evidenceDate + _ageStr;
    } else {
        _dateStr = 'Date not detected — conservative age estimate applied';
    }

    doc.setFont('helvetica', 'italic'); doc.setFontSize(6.5);
    doc.setTextColor(_fresh.color[0], _fresh.color[1], _fresh.color[2]);
    doc.text(_fresh.label + '  ' + _dateStr, x, y);
}


// ══════════════════════════════════════════════════════════════
// SECTION 9: Supabase columns
// ══════════════════════════════════════════════════════════════

const TIME_DECAY_SQL = `
ALTER TABLE hai_analysis_logs
    ADD COLUMN IF NOT EXISTS avg_evidence_freshness  INTEGER DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS stale_evidence_count    INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS current_evidence_count  INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS active_cert_count       INTEGER DEFAULT 0;

CREATE OR REPLACE VIEW v_freshness_vs_score AS
SELECT
    industry,
    ROUND(AVG(avg_evidence_freshness)::numeric, 1) AS avg_freshness_pct,
    ROUND(AVG(final_score)::numeric, 1)            AS avg_score,
    COUNT(*)                                        AS assessment_count
FROM hai_analysis_logs
WHERE avg_evidence_freshness IS NOT NULL
  AND final_score IS NOT NULL
GROUP BY industry
ORDER BY avg_freshness_pct DESC;
`;


module.exports = {
    DECAY_CURVES,
    DEFAULT_AGE_MONTHS_WHEN_UNDATED,
    parseEvidenceDate,
    parseCertValidUntil,
    ageInMonths,
    timeDecayMultiplier,
    annotateWithTimeDecay,
    computeOverallFreshness,
    getFreshnessLabel,
    renderEvidenceFreshnessLabel,
    TIME_DECAY_SQL
};
