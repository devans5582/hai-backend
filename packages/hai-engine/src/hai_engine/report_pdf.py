"""The PDF rendering of a report.

Takes the dictionary that ``build_report`` returns and lays it out as the
printable HAI Score report: cover, how the organization was evaluated,
alignment snapshot, one page per pillar, verification and monitoring,
evidence and certification, evidence gaps, and the evidence appendix. The
structure follows Humaital's published HAI Report (Rubric v2) and the content
is what methodology 2.0.0 records: the evidence ladder, focus-area coverage,
control verification, incident timelines, impact measures and the confidence
components.

Everything printed is read from the report. Nothing here computes a level, a
score or a status (AT-10); the few arithmetic lines are percentages for bars
and counts of rows already present. Remediation advice is not generated: the
report states where evidence is missing and leaves the guidance to Humaital.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import TableBordersLayout, TableCellFillMode, XPos, YPos
from fpdf.fonts import FontFace

from hai_core.generated.enums import LABELS, RANKS, Admissibility, CertificationOutcome, OutcomeStatus, Polarity

ASSETS = Path(__file__).parent / "assets"
FONTS = ASSETS / "fonts"
LOGO = ASSETS / "humaital-logo.png"

RED = (199, 53, 66)
DARK = (31, 41, 51)
BODY = (55, 65, 81)
GREY = (107, 114, 128)
MUTED = (156, 163, 175)
LINE = (222, 226, 230)
PANEL = (246, 247, 249)
PANEL_RED = (253, 243, 244)
PANEL_AMBER = (255, 249, 230)
AMBER = (176, 108, 0)
GREEN = (22, 120, 60)
BLUE = (30, 80, 160)
WHITE = (255, 255, 255)

# Tone by rank of the maturity status (needs attention, developing, progressing, strong).
STATUS_TONE_BY_RANK = {0: RED, 1: AMBER, 2: BLUE, 3: GREEN}
# Tone by rank of the maturity rung (none up to independently verified).
RUNG_TONE_BY_RANK = {0: MUTED, 1: AMBER, 2: AMBER, 3: BLUE, 4: GREEN}

WHAT_THIS_MEANS = [
    "HAI Score reflects the maturity of human-first governance across six pillars.",
    "Evidence confidence reflects the strength and reliability of publicly available evidence found.",
    "Evidence coverage reflects how many distinct public sources were reached.",
]
SCOPE_NOTE = (
    "This assessment evaluates verifiable public evidence, not internal practices. Absence of evidence "
    "means that no publicly accessible documentation was found, not that the capability does not exist "
    "internally. Organizations can improve their score by making governance practices visible, "
    "structured and verifiable."
)
CLOSING_NOTE = (
    "The {long_name} score represents an analytical evaluation based on publicly available information "
    "and the Humaital HAI methodology. Scores are intended to encourage responsible governance and may "
    "evolve as additional information becomes available. Every figure in this report traces to a stored "
    "decision, a frozen evidence snapshot and quoted spans; the identifiers on the certification page "
    "reproduce it."
)

Rgb = tuple[int, int, int]


def _s(value: Any, empty: str = "-") -> str:
    if value is None or value == "" or value == []:
        return empty
    return str(value)


def _num(value: Any, digits: int = 1, empty: str = "n/a") -> str:
    if value is None:
        return empty
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{f:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{f:.0f}"


def _pct(value: Any, empty: str = "n/a") -> str:
    return empty if value is None else f"{float(value):.0f}%"


def _date(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    return text[:10]


def _label(vocabulary: str, code: Any) -> str:
    if code is None:
        return "-"
    return LABELS.get(vocabulary, {}).get(str(code), str(code).replace("_", " ").capitalize())


def _labels(vocabulary: str, codes: Any) -> str:
    items = [_label(vocabulary, c) for c in (codes or [])]
    return ", ".join(items) if items else "-"


def _clip(text: Any, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-") or "organization"


def report_filename(report: dict[str, Any]) -> str:
    org = _slug(str(report.get("organization", {}).get("name") or "organization"))
    version = report.get("version") or {}
    product = _slug(str(report.get("product", {}).get("report_name") or "HAI Score"))
    return f"{product}-{org}-v{version.get('number', 1)}.pdf"


def _is_support(link: dict[str, Any]) -> bool:
    return (
        link.get("admissibility") == Admissibility.ADMISSIBLE.value and link.get("polarity") == Polarity.SUPPORTS.value
    )


class ReportPDF(FPDF):
    """A4 portrait with the Humaital wordmark on every page and a running footer."""

    def __init__(self, report: dict[str, Any], website: str, tagline: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.report = report
        self.website = website
        self.tagline = tagline
        self.cover = True
        self.set_margins(18, 24, 18)
        self.set_auto_page_break(auto=True, margin=22)
        self.add_font("Sans", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("Sans", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.add_font("Sans", "I", str(FONTS / "DejaVuSans-Oblique.ttf"))
        self.alias_nb_pages()
        methodology = report.get("assessment", {}).get("versions", {}).get("methodology", "")
        self.rubric = f"Methodology {methodology}" if methodology else "Methodology"
        self.set_title(f"{report['product']['report_name']} report: {report['organization']['name']}")
        self.set_author("Humaital")
        self.set_subject(report["product"]["long_name"])
        self.set_creator("HAI Score platform")

    # ----------------------------------------------------------------- chrome
    def header(self) -> None:
        if LOGO.exists():
            self.image(str(LOGO), x=self.l_margin, y=8, h=9)
        self.set_draw_color(*RED)
        self.set_line_width(0.5)
        self.line(self.l_margin, 19, self.w - self.r_margin, 19)
        self.set_y(24)

    def footer(self) -> None:
        self.set_y(-15)
        self.font(8, GREY)
        parts = [f"Page {self.page_no()} of {{nb}}", self.website, self.tagline, self.rubric]
        self.cell(0, 5, "  |  ".join(parts), align="L")
        self.cell(0, 5, _clip(self.report["organization"]["name"], 40), align="R")

    # ----------------------------------------------------------------- helpers
    def font(self, size: float, color: Rgb = BODY, style: str = "") -> None:
        self.set_font("Sans", style, size)
        self.set_text_color(*color)

    def h1(self, text: str) -> None:
        self.font(17, DARK, "B")
        self.cell(0, 9, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def h2(self, text: str, color: Rgb = RED) -> None:
        self.ensure(16)
        self.ln(2)
        self.font(11.5, color, "B")
        self.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)

    def h3(self, text: str) -> None:
        self.ensure(12)
        self.font(10, DARK, "B")
        self.cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text: str, size: float = 9, color: Rgb = BODY, style: str = "", gap: float = 1.5) -> None:
        self.font(size, color, style)
        self.multi_cell(0, size * 0.52, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(gap)

    def bullets(self, items: list[str], size: float = 9, color: Rgb = BODY) -> None:
        for item in items:
            self.font(size, color)
            x = self.get_x()
            self.cell(5, size * 0.52, "•")
            self.multi_cell(self.epw - 5, size * 0.52, item, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_x(x)
        self.ln(1)

    def rule(self, gap: float = 3) -> None:
        self.ln(gap / 2)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(gap / 2)

    def ensure(self, height: float) -> None:
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def kv(self, rows: list[tuple[str, str]], key_width: float = 48, size: float = 9.5) -> None:
        """Label and value pairs; the value in bold, as the cover of the published report."""
        for key, value in rows:
            self.ensure(8)
            self.font(size, GREY)
            self.cell(key_width, 7, key)
            self.font(size, DARK, "B")
            self.multi_cell(0, 7, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def panel(self, title: str, body: list[str], fill: Rgb = PANEL, accent: Rgb = DARK) -> None:
        """A boxed note: title in the accent color, then lines of body text."""
        line_h = 4.6
        self.font(8.8)
        lines = 0
        for b in body:
            wrapped = self.multi_cell(self.epw - 8, line_h, b, dry_run=True, output="LINES")
            lines += len(wrapped) if isinstance(wrapped, list) else 1
        height = 9 + lines * line_h + 2.5 * len(body) + 3
        self.ensure(height)
        x, y = self.l_margin, self.get_y()
        self.set_fill_color(*fill)
        self.set_draw_color(*accent)
        self.set_line_width(0.3)
        self.rect(x, y, self.epw, height, style="DF")
        self.set_xy(x + 4, y + 3)
        self.font(9.5, accent, "B")
        self.cell(0, 6, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for b in body:
            self.set_x(x + 4)
            self.font(8.8)
            self.multi_cell(self.epw - 8, line_h, b, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(2.5)
        self.set_y(y + height + 3)

    def bar(self, x: float, y: float, w: float, share: float, color: Rgb = GREEN, h: float = 3.2) -> None:
        self.set_fill_color(*LINE)
        self.rect(x, y, w, h, style="F")
        if share > 0:
            self.set_fill_color(*color)
            self.rect(x, y, max(0.8, w * min(1.0, share)), h, style="F")

    def grid(
        self,
        headings: list[str],
        rows: list[list[str | tuple[str, FontFace]]],
        widths: list[float],
        align: list[str] | None = None,
        size: float = 8.6,
        heading_fill: Rgb = RED,
    ) -> None:
        if not rows:
            self.para("None recorded.", 8.6, MUTED, "I")
            return
        self.font(size)
        head = FontFace(emphasis="BOLD", color=WHITE, fill_color=heading_fill)
        with self.table(
            col_widths=widths,
            text_align=align or ["LEFT"] * len(widths),
            borders_layout=TableBordersLayout.HORIZONTAL_LINES,
            cell_fill_color=PANEL,
            cell_fill_mode=TableCellFillMode.ROWS,
            headings_style=head,
            line_height=size * 0.55,
            padding=(1.6, 1.8),
        ) as table:
            row = table.row()
            for h in headings:
                row.cell(h)
            for r in rows:
                row = table.row()
                for cell in r:
                    if isinstance(cell, tuple):
                        row.cell(cell[0], style=cell[1])
                    else:
                        row.cell(cell)
        self.ln(2)

    # ----------------------------------------------------------------- tones
    def status_tone(self, status: str | None) -> Rgb:
        if status is None:
            return MUTED
        return STATUS_TONE_BY_RANK.get(RANKS.get("maturity_status", {}).get(status, 0), MUTED)

    def rung_tone(self, rung: str | None) -> Rgb:
        if rung is None:
            return MUTED
        return RUNG_TONE_BY_RANK.get(RANKS.get("maturity_rung", {}).get(rung, 0), MUTED)

    def outcome_tone(self, status: str | None) -> Rgb:
        return GREEN if status == OutcomeStatus.HAI_CERTIFIED.value else RED


def _executive_summary(r: dict[str, Any]) -> str:
    org = r["organization"]["name"]
    result = r.get("result")
    scale = r.get("scale", {})
    coverage = r.get("coverage_summary", {})
    counted = r.get("evidence_basis", {}).get("criteria_counted", 0)
    total = len(r.get("criteria", []))
    if not result:
        state = r.get("assessment", {}).get("lifecycle_label") or "in progress"
        return (
            f"{org} has no result yet; the assessment is {str(state).lower()}. The sections that follow show the "
            f"sources reached so far and the criteria that will be evaluated."
        )
    statuses: dict[str, int] = {}
    for p in r.get("pillars", []):
        if p.get("status_label"):
            statuses[p["status_label"]] = statuses.get(p["status_label"], 0) + 1
    status_text = ", ".join(f"{n} {label.lower()}" for label, n in statuses.items()) or "not yet determined"
    cov = ", ".join(f"{n} {_label('coverage_state', k).lower()}" for k, n in coverage.items() if n)
    text = (
        f"{org} scored {_num(result.get('hai_score'))} / {_num(scale.get('score_scale', 100), 0)} with evidence "
        f"confidence {_pct(result.get('confidence_pct'))}. Outcome: {result.get('outcome_label')}. "
        f"{counted} of {total} criteria entered the score ({cov}). Pillar status: {status_text}."
    )
    if result.get("gate_reasons"):
        text += " Gates: " + "; ".join(str(g) for g in result["gate_reasons"]) + "."
    if result.get("caps_applied"):
        text += " Caps applied: " + ", ".join(str(c) for c in result["caps_applied"]) + "."
    return text


def _position_text(benchmark: dict[str, Any] | None) -> str:
    if not benchmark:
        return "No peer group yet"
    pos = benchmark.get("position")
    word = {"above": "Above", "below": "Below", "at": "At"}.get(str(pos), "Not compared")
    return (
        f"{word} peer average ({benchmark['industry_label']} average {_num(benchmark['average_score'])}, "
        f"{benchmark['organizations']} organization{'s' if benchmark['organizations'] != 1 else ''})"
    )


# ------------------------------------------------------------------- pages
def _cover(pdf: ReportPDF, r: dict[str, Any]) -> None:
    pdf.add_page()
    a, org, result = r["assessment"], r["organization"], r.get("result")
    scale = r.get("scale", {})
    pdf.ln(4)
    pdf.font(14, DARK, "B")
    pdf.cell(
        0,
        8,
        f"{r['product']['long_name']} Assessment: {r['product']['report_name']}",
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(4)
    pdf.font(8.6, GREY)
    pdf.multi_cell(
        0,
        4.4,
        f"The {r['product']['long_name']} evaluates governance, responsibility and human-first alignment in AI "
        "deployments. The score reflects the maturity of governance practices across the HAI pillars. Evidence "
        "confidence reflects the strength of verified evidence; evidence coverage reflects the breadth of public "
        "sources reached.",
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(10)
    if result:
        pdf.font(44, RED, "B")
        score = _num(result.get("hai_score"))
        pdf.cell(0, 18, score, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.font(10, GREY)
        pdf.cell(
            0, 6, f"out of {_num(scale.get('score_scale', 100), 0)}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        pdf.ln(2)
        pdf.font(11, DARK)
        pdf.cell(
            0,
            6,
            f"Evidence confidence: {_pct(result.get('confidence_pct'))}",
            align="C",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(1)
        pdf.font(11, pdf.outcome_tone(result.get("outcome_status")), "B")
        pdf.cell(0, 7, str(result.get("outcome_label", "")).upper(), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        pdf.font(26, MUTED, "B")
        pdf.cell(0, 14, "No result yet", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.font(10, GREY)
        pdf.cell(0, 6, str(a.get("lifecycle_label", "")), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(8)
    pdf.rule(4)
    version = r.get("version") or {}
    pdf.kv(
        [
            ("Company", _s(org.get("name"))),
            ("Website", _s(org.get("domain"))),
            ("Industry", _label("industry", org.get("industry_code"))),
            ("Stage", _label("stage_band", a.get("stage_band"))),
            ("Size", _label("size_band", a.get("size_band"))),
            ("Assessment version", f"{version.get('number', 1)} of {version.get('total', 1)}"),
            ("Assessed", _date(a.get("finished_at") or a.get("created_at"))),
            ("Benchmark position", _position_text(r.get("benchmark"))),
        ]
    )
    pdf.rule(4)
    pdf.h2("Executive Summary")
    pdf.para(_executive_summary(r), 9.5)
    pdf.rule(3)
    pdf.h2("What This Means")
    pdf.bullets(WHAT_THIS_MEANS, 9)
    cert = r.get("certification")
    if cert:
        pdf.rule(3)
        pdf.h2("Certification")
        if cert["decision"] == CertificationOutcome.CERTIFIED.value:
            pdf.para(
                f"Certified by reviewer {cert['reviewer_id']} on {_date(cert['signed_at'])}, certificate "
                f"{cert.get('certificate_number') or '-'}, valid until {_date(cert.get('expires_at'))}.",
                9.5,
                GREEN,
                "B",
            )
        else:
            pdf.para(
                f"{cert['decision_label']} by reviewer {cert['reviewer_id']} on {_date(cert['signed_at'])}."
                + (" Reasons: " + "; ".join(cert["gate_reasons"]) + "." if cert.get("gate_reasons") else ""),
                9.5,
            )


def _how_evaluated(pdf: ReportPDF, r: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.h1("How We Evaluated You")
    pdf.para(
        "This page documents the sources reached, the evidence types used, the depth of analysis and the "
        "evidence ladder that formed the basis of the score.",
        9,
        GREY,
    )
    pdf.h2("A. Sources Reached")
    runs = r.get("connector_runs", [])
    sources = r.get("sources", [])
    by_connector: dict[str, int] = {}
    for s in sources:
        by_connector[str(s.get("connector"))] = by_connector.get(str(s.get("connector")), 0) + 1
    items = []
    for run in runs:
        outcome = _label("connector_run_outcome", run.get("outcome"))
        docs = by_connector.get(str(run.get("code")), 0)
        detail = f"{docs} document{'s' if docs != 1 else ''} collected" if docs else outcome
        if run.get("error_code"):
            detail += f" ({run['error_code']})"
        items.append(f"{run.get('name') or run.get('code')}: {detail}")
    if items:
        pdf.bullets(items, 8.8)
    else:
        pdf.para("No connector has run yet.", 8.8, MUTED, "I")

    pdf.h2("B. Evidence Types Used")
    strength = r.get("evidence_strength", {})
    rows: list[list[str | tuple[str, FontFace]]] = []
    for cls in r.get("evidence_classes", []):
        st = strength.get(cls["code"], {})
        rows.append(
            [
                (cls["label"], FontFace(emphasis="BOLD", color=DARK)),
                cls.get("description", ""),
                f"{st.get('criteria_with_evidence', 0)} criteria",
            ]
        )
    pdf.grid(["Evidence type", "What it covers", "Present for"], rows, [42, 100, 32])

    pdf.h2("C. Depth Of Analysis")
    links = [link for c in r.get("criteria", []) for link in c.get("evidence", [])]
    admissible = [link for link in links if link.get("admissibility") == Admissibility.ADMISSIBLE.value]
    supports = [link for link in admissible if link.get("polarity") == Polarity.SUPPORTS.value]
    contradicts = [link for link in admissible if link.get("polarity") == Polarity.CONTRADICTS.value]
    domains = {
        str(s.get("canonical_url", "")).split("/")[2] for s in sources if "//" in str(s.get("canonical_url", ""))
    }
    coverage = r.get("coverage_summary", {})
    pdf.kv(
        [
            ("Documents collected", str(len(sources))),
            ("Distinct domains", str(len(domains))),
            ("Evidence links frozen", str(len(links))),
            ("Admissible links", f"{len(admissible)} ({len(supports)} supporting, {len(contradicts)} contradicting)"),
            (
                "Criteria counted in score",
                f"{r.get('evidence_basis', {}).get('criteria_counted', 0)} of {len(r.get('criteria', []))}",
            ),
            (
                "Criteria by coverage",
                ", ".join(f"{n} {_label('coverage_state', k).lower()}" for k, n in coverage.items() if n) or "-",
            ),
        ],
        key_width=58,
        size=9,
    )

    pdf.h2("D. Evidence Ladder")
    pdf.para(
        "Each admissible supporting quote sits on one rung. Higher rungs prove more: a statement of intent, a "
        "specified control, dated execution, then independent verification. Counts are links, not points.",
        8.6,
        GREY,
    )
    basis = r.get("evidence_basis", {})
    by_rung = basis.get("by_rung", {})
    total_links = sum(int(v) for v in by_rung.values()) or 1
    for rung in r.get("rung_definitions", []) or [{"code": k, "label": v} for k, v in basis.get("labels", {}).items()]:
        n = int(by_rung.get(rung["code"], 0))
        pdf.ensure(8)
        y = pdf.get_y()
        pdf.font(8.8, DARK, "B")
        pdf.cell(48, 6, rung["label"])
        pdf.bar(pdf.l_margin + 50, y + 1.6, 80, n / total_links, pdf.rung_tone(rung["code"]))
        pdf.set_x(pdf.l_margin + 134)
        pdf.font(8.8, BODY)
        pdf.cell(0, 6, f"{n} link{'s' if n != 1 else ''}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.panel("Important: scope of this assessment", [SCOPE_NOTE], PANEL_AMBER, AMBER)


def _snapshot(pdf: ReportPDF, r: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.h1("Alignment Snapshot")
    pdf.h3("HAI Governance Profile")
    pdf.para(
        "Your alignment across the six HAI pillars based on the frozen evidence. Scores are pillar means on the "
        "methodology's scale; weights are the share each pillar carries in the HAI Score.",
        9,
        GREY,
    )
    scale = r.get("scale", {})
    rows: list[list[str | tuple[str, FontFace]]] = []
    for p in r.get("pillars", []):
        tone = pdf.status_tone(p.get("status"))
        rows.append(
            [
                (p["name"], FontFace(emphasis="BOLD", color=DARK)),
                f"{_num(p.get('score'))} / {_num(scale.get('score_scale', 100), 0)}",
                f"{float(p.get('weight') or 0) * 100:.0f}%",
                (_s(p.get("status_label"), "Not yet determined"), FontFace(emphasis="BOLD", color=tone)),
                _pct(p.get("confidence")),
                f"{p.get('criteria_counted', 0)} counted, {p.get('criteria_excluded', 0)} excluded",
            ]
        )
    pdf.grid(["Pillar", "Score", "Weight", "Status", "Confidence", "Criteria"], rows, [34, 24, 18, 34, 24, 40])
    pdf.h3("Status Definitions")
    for d in r.get("status_definitions", []):
        pdf.font(8.6, pdf.status_tone(d["code"]), "B")
        pdf.cell(34, 5, d["label"])
        pdf.font(8.6, BODY)
        pdf.multi_cell(0, 5, d["wording"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.rule(3)
    pdf.h2("Focus Area Coverage")
    pdf.para(
        "The seven areas the methodology looks at beyond documented policy: how many criteria each bears on, how "
        "many admissible supporting quotes were tagged to it and the highest rung they reach. Coverage is "
        "reported; it never changes a weight.",
        8.6,
        GREY,
    )
    rows = []
    for fa in r.get("focus_areas", []):
        best = fa.get("best_rung")
        rows.append(
            [
                (fa["label"], FontFace(emphasis="BOLD", color=DARK)),
                _clip(fa.get("question", ""), 110),
                str(len(fa.get("criteria", []))),
                str(fa.get("links", 0)),
                (_s(fa.get("best_rung_label"), "No evidence"), FontFace(emphasis="BOLD", color=pdf.rung_tone(best))),
            ]
        )
    pdf.grid(["Focus area", "Question", "Criteria", "Links", "Highest rung"], rows, [40, 64, 18, 14, 38])
    strength = r.get("evidence_strength", {})
    counted = r.get("evidence_basis", {}).get("criteria_counted", 0)
    if strength:
        pdf.h3("Evidence Strength")
        rows = []
        for cls in r.get("evidence_classes", []) or [{"code": k, "label": v["label"]} for k, v in strength.items()]:
            st = strength.get(cls["code"])
            if not st:
                continue
            rows.append(
                [
                    (cls["label"], FontFace(emphasis="BOLD", color=DARK)),
                    st["strength"],
                    f"{st['criteria_with_evidence']} of {counted} counted criteria ({float(st['share']) * 100:.0f}%)",
                ]
            )
        pdf.grid(["Evidence type", "Strength", "Criteria with this evidence"], rows, [50, 36, 88])
    pdf.para("Results use the methodology's pillar weights for the organization's stage profile.", 8, MUTED, "I")


def _pillar_pages(pdf: ReportPDF, r: dict[str, Any]) -> None:
    scale = r.get("scale", {})
    level_max = scale.get("level_max", 5)
    criteria_by_pillar: dict[str, list[dict[str, Any]]] = {}
    for c in r.get("criteria", []):
        criteria_by_pillar.setdefault(str(c["pillar"]), []).append(c)
    for p in r.get("pillars", []):
        pdf.add_page()
        pdf.h1(f"{p['name']} Analysis")
        # pillar header box
        y = pdf.get_y()
        pdf.set_fill_color(*PANEL_RED)
        pdf.set_draw_color(*RED)
        pdf.set_line_width(0.4)
        pdf.rect(pdf.l_margin, y, pdf.epw, 17, style="DF")
        pdf.set_xy(pdf.l_margin + 4, y + 3)
        pdf.font(13, RED, "B")
        pdf.cell(60, 11, p["name"])
        weight_pct = f"{float(p.get('weight') or 0) * 100:.0f}"
        pdf.set_xy(pdf.l_margin + 66, y + 2.5)
        pdf.font(8.8, BODY)
        pdf.cell(
            60,
            5.5,
            f"Score: {_num(p.get('score'))} / {_num(scale.get('score_scale', 100), 0)}  (weight {weight_pct}%)",
            new_x=XPos.LEFT,
            new_y=YPos.NEXT,
        )
        pdf.font(8.8, pdf.status_tone(p.get("status")), "B")
        pdf.cell(60, 5.5, f"Status: {_s(p.get('status_label'), 'Not yet determined')}")
        pdf.set_xy(pdf.l_margin + 128, y + 2.5)
        pdf.font(8.8, BODY)
        pdf.cell(0, 5.5, f"Evidence confidence: {_pct(p.get('confidence'))}", new_x=XPos.LEFT, new_y=YPos.NEXT)
        pdf.cell(0, 5.5, f"{p.get('criteria_counted', 0)} criteria counted, {p.get('criteria_excluded', 0)} excluded")
        pdf.set_y(y + 21)
        if p.get("status_wording"):
            pdf.para(str(p["status_wording"]), 8.6, GREY, "I")

        for c in criteria_by_pillar.get(str(p["code"]), []):
            _criterion_block(pdf, c, level_max)

        gaps = _pillar_gaps(criteria_by_pillar.get(str(p["code"]), []))
        if gaps:
            pdf.panel(f"Evidence gaps: {p['name']}", gaps, PANEL_AMBER, AMBER)


def _criterion_block(pdf: ReportPDF, c: dict[str, Any], level_max: int) -> None:
    pdf.ensure(34)
    pdf.rule(2)
    y = pdf.get_y()
    pdf.font(10, DARK, "B")
    name = _clip(c["name"], 48)
    pdf.cell(pdf.get_string_width(name) + 2, 6, name)
    pdf.font(7.5, MUTED)
    pdf.cell(0, 6, str(c["code"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(pdf.l_margin + 104, y)
    level = c.get("level")
    best = c.get("best_rung")
    pdf.font(9.5, BLUE if level else MUTED, "B")
    pdf.cell(30, 6, f"L{level} / {level_max}" if level is not None else "Not levelled")
    pdf.font(9, pdf.rung_tone(best), "B")
    confidence = f"Confidence {_pct(c.get('confidence'))}" if c.get("confidence") is not None else ""
    pdf.cell(0, 6, confidence, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    coverage = c.get("coverage_state")
    pdf.font(8.4, GREY)
    pdf.cell(104, 5, f"Coverage: {_label('coverage_state', coverage)}" if coverage else "Coverage: not yet decided")
    basis = c.get("evidence_basis") or {}
    ladder = ", ".join(f"{_label('maturity_rung', k).lower()} {v}" for k, v in basis.items() if v)
    pdf.cell(
        0,
        5,
        f"Ladder: {ladder}" if ladder else "Ladder: no admissible supporting evidence",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    if c.get("focus_areas"):
        pdf.font(8, MUTED)
        pdf.cell(
            0,
            4.5,
            "Focus areas: " + ", ".join(_label("focus_area", f) for f in c["focus_areas"]),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    pdf.ln(1)
    if c.get("level_descriptor"):
        suffix = " (draft descriptor)" if c.get("content_status") == "draft" else ""
        _found_line(pdf, "Level", _clip(c["level_descriptor"], 400) + suffix, BLUE)
    supports = [link for link in c.get("evidence", []) if _is_support(link)]
    supports.sort(key=lambda link: RANKS.get("maturity_rung", {}).get(str(link.get("maturity_rung")), 0), reverse=True)
    for link in supports[:2]:
        source = " / ".join(x for x in (link.get("publisher_name"), link.get("document_title")) if x)
        rung = _label("maturity_rung", link.get("maturity_rung"))
        meta = f" [{rung}; {source or 'source'}; {_date(link.get('published_at'))}]"
        _found_line(pdf, "Found", f"“{_clip(link.get('quote'), 320)}”{meta}", GREEN)
    if not supports:
        _found_line(
            pdf, "Found", _s(c.get("coverage_wording"), "No admissible supporting evidence in public sources."), GREY
        )
    contradicting = [
        link
        for link in c.get("evidence", [])
        if link.get("admissibility") == Admissibility.ADMISSIBLE.value
        and link.get("polarity") == Polarity.CONTRADICTS.value
    ]
    if contradicting:
        _found_line(
            pdf,
            "Contradicts",
            f"{len(contradicting)} admissible quote{'s' if len(contradicting) != 1 else ''} contradict this criterion; "
            "see the appendix.",
            RED,
        )
    gap = _criterion_gap(c)
    if gap:
        _found_line(pdf, "Gap", gap, AMBER)
    if c.get("review_required"):
        _found_line(pdf, "Review", "A named reviewer must look at this criterion before it is final.", RED)


def _found_line(pdf: ReportPDF, key: str, text: str, color: Rgb) -> None:
    pdf.ensure(10)
    x = pdf.get_x()
    pdf.font(8.4, color, "B")
    pdf.cell(24, 4.6, key + ":")
    pdf.font(8.4, BODY)
    pdf.multi_cell(pdf.epw - 24, 4.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(x)
    pdf.ln(0.8)


def _rungs_above(best: str | None) -> list[str]:
    ranks = RANKS.get("maturity_rung", {})
    best_rank = ranks.get(str(best), 0) if best else 0
    return [
        _label("maturity_rung", code).lower()
        for code, rank in sorted(ranks.items(), key=lambda kv: kv[1])
        if rank > max(best_rank, 0)
    ]


def _criterion_gap(c: dict[str, Any]) -> str | None:
    """A factual statement of what public evidence did not show. No remediation advice."""
    supports = [link for link in c.get("evidence", []) if _is_support(link)]
    if c.get("coverage_state") is None:
        return None
    if not supports:
        return "No admissible public evidence supports this criterion."
    above = _rungs_above(c.get("best_rung"))
    if not above:
        return None
    return (
        "Highest rung reached: "
        + _label("maturity_rung", c.get("best_rung")).lower()
        + ". Not evidenced: "
        + ", ".join(above)
        + "."
    )


def _pillar_gaps(criteria: list[dict[str, Any]]) -> list[str]:
    out = []
    for c in criteria:
        gap = _criterion_gap(c)
        if gap:
            out.append(f"{c['name']}: {gap}")
    return out


def _verification_page(pdf: ReportPDF, r: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.h1("Verification, Monitoring, Incidents And Impact")
    pdf.para(
        "Structured evidence frozen with the snapshot: the controls the organization claims, the tests that "
        "exercised them, how its AI systems are monitored, how incidents were handled and whether impact is "
        "measured. A claimed stop capability without a passing exercise cannot be levelled as executed (IC-19).",
        9,
        GREY,
    )
    v = r.get("verification", {})
    pdf.h2("Verification Of AI Controls")
    rows: list[list[str | tuple[str, FontFace]]] = []
    for c in v.get("controls", []):
        unexercised = c.get("unexercised_capabilities") or []
        rows.append(
            [
                (_s(c.get("name"), c.get("control_id", "")), FontFace(emphasis="BOLD", color=DARK)),
                _labels("control_capability", c.get("claimed_capabilities")),
                (
                    _labels("control_capability", c.get("exercised_capabilities")),
                    FontFace(color=GREEN if c.get("exercised_capabilities") else MUTED),
                ),
                (
                    _labels("control_capability", unexercised),
                    FontFace(emphasis="BOLD" if unexercised else None, color=AMBER if unexercised else MUTED),
                ),
                _label("observability", c.get("monitoring_mode")),
                str(c.get("tests", 0)),
            ]
        )
    pdf.grid(
        ["Control", "Claimed", "Exercised by a passing test", "Not exercised", "Monitoring", "Tests"],
        rows,
        [36, 32, 34, 32, 26, 14],
    )
    if v.get("controls"):
        pdf.para(
            f"{v.get('controls_with_unexercised_capabilities', 0)} of {len(v['controls'])} controls claim a capability "
            "that no passing test exercised.",
            8.6,
            AMBER if v.get("controls_with_unexercised_capabilities") else GREY,
        )

    pdf.h2("Containment And Security Testing")
    methods = v.get("tests_by_method", {})
    threats = v.get("threats_exercised", {})
    if methods or threats:
        pdf.kv(
            [
                (
                    "Tests by method",
                    ", ".join(f"{_label('verification_method', k)} {n}" for k, n in methods.items()) or "-",
                ),
                (
                    "Threats exercised",
                    ", ".join(f"{_label('containment_threat', k)} {n}" for k, n in threats.items()) or "none recorded",
                ),
            ],
            key_width=42,
            size=9,
        )
    else:
        pdf.para("No test outcome is recorded in public evidence.", 8.6, MUTED, "I")

    pdf.h2("Autonomous AI Monitoring")
    rows = []
    for s in v.get("ai_systems", []):
        rows.append(
            [
                (_s(s.get("name"), s.get("system_id", "")), FontFace(emphasis="BOLD", color=DARK)),
                _label("autonomy_level", s.get("autonomy_level")),
                _label("observability", s.get("monitoring_mode")),
                _label("criticality", s.get("criticality")),
            ]
        )
    pdf.grid(["AI system", "Autonomy", "Monitoring", "Criticality"], rows, [66, 36, 42, 30])

    pdf.h2("Incident Response And Recovery")
    rows = []
    for i in r.get("incident_response", []):
        rows.append(
            [
                (_clip(_s(i.get("title"), i.get("incident_id", "")), 60), FontFace(emphasis="BOLD", color=DARK)),
                _label("incident_status", i.get("status")),
                _label("incident_severity", i.get("severity")),
                _s(i.get("days_to_disclose")),
                _s(i.get("days_to_contain")),
                _s(i.get("days_to_correct")),
                (
                    "Yes" if i.get("correction_verified") else "No",
                    FontFace(emphasis="BOLD", color=GREEN if i.get("correction_verified") else AMBER),
                ),
            ]
        )
    pdf.grid(
        ["Incident", "Status", "Severity", "Disclose (d)", "Contain (d)", "Correct (d)", "Fix verified"],
        rows,
        [48, 26, 22, 20, 20, 20, 18],
    )

    pdf.h2("Human Benefit And Measurable Impact")
    im = r.get("impact_measures", {})
    if im.get("items"):
        pdf.para(
            f"{im.get('demonstrated_benefit', 0)} of {im.get('total', 0)} impact measures demonstrate an outcome "
            "rather than an intention or an output count.",
            8.8,
        )
        rows = []
        for m in im["items"]:
            rows.append(
                [
                    (_clip(m.get("outcome"), 90), FontFace(color=DARK)),
                    _label("impact_evidence_kind", m.get("kind")),
                    "Yes" if m.get("demonstrates_benefit") else "No",
                    "Yes" if m.get("verified_independently") else "No",
                    _date(m.get("measured_at")),
                ]
            )
        pdf.grid(
            ["Outcome", "Kind", "Benefit shown", "Verified", "Measured"],
            rows,
            [70, 36, 24, 22, 22],
        )
    else:
        pdf.para("No impact measure is recorded in public evidence.", 8.6, MUTED, "I")


def _evidence_page(pdf: ReportPDF, r: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.h1("Evidence, Confidence And Certification")
    result = r.get("result")
    scale = r.get("scale", {})
    pdf.h2("Evidence Summary")
    strength = r.get("evidence_strength", {})
    rows: list[list[str | tuple[str, FontFace]]] = [
        [(v["label"], FontFace(emphasis="BOLD", color=DARK)), v["strength"], f"{v['criteria_with_evidence']} criteria"]
        for v in strength.values()
    ]
    pdf.grid(["Evidence type", "Strength", "Present for"], rows, [60, 40, 74])
    pdf.para("This assessment is based on identifiable, publicly available governance evidence.", 8.8, GREY)

    pdf.h2("About Evidence Confidence")
    cm = r.get("confidence_methodology", {})
    weights = cm.get("weights", {})
    pdf.para(
        "Confidence is computed from the frozen evidence links only. Each admissible supporting link earns credit "
        "for the credibility of its source, the type of evidence it is (a statement earns less than dated execution, "
        "which earns less than independent verification), agreement across independent sources and recency. The "
        "components and their weights come from the published methodology.",
        8.8,
    )
    if weights:
        rows = [
            [(k.replace("_", " ").capitalize(), FontFace(emphasis="BOLD", color=DARK)), f"{float(w) * 100:.0f}%"]
            for k, w in weights.items()
        ]
        pdf.grid(["Component", "Weight"], rows, [120, 54], align=["LEFT", "RIGHT"])
    credit = cm.get("evidence_type_credit", {})
    if credit:
        pdf.para(
            "Evidence type credit by rung: "
            + ", ".join(f"{_label('maturity_rung', k).lower()} {float(v):.2f}" for k, v in credit.items())
            + ".",
            8.4,
            GREY,
        )

    pdf.h2("Score Composition")
    if result:
        pdf.kv(
            [
                ("HAI Score", f"{_num(result.get('hai_score'))} / {_num(scale.get('score_scale', 100), 0)}"),
                ("Score before caps", _num(result.get("score_before_caps"))),
                ("Caps applied", ", ".join(result.get("caps_applied") or []) or "none"),
                ("Effectiveness", _num(result.get("effectiveness"))),
                ("Evidence confidence", _pct(result.get("confidence_pct"))),
                ("Outcome", _s(result.get("outcome_label"))),
                ("Gate reasons", "; ".join(result.get("gate_reasons") or []) or "none"),
                ("Review triggers", ", ".join(result.get("review_triggers") or []) or "none"),
            ],
            key_width=46,
            size=9,
        )
    else:
        pdf.para("No result has been produced yet.", 8.8, MUTED, "I")
    pdf.para(
        f"The score is criterion-evaluated: each of the {len(r.get('criteria', []))} criteria is levelled from "
        "admissible "
        "evidence by the rules engine, pillar means are weighted by criterion materiality and the HAI Score is the "
        "weighted sum of the pillars. Nothing enters the score except through an evidence link naming one quote, "
        "one target and one criterion.",
        8.6,
        GREY,
    )

    pdf.h2("Certification Readiness")
    cert = r.get("certification")
    threshold = scale.get("certification_threshold")
    min_conf = scale.get("min_confidence")
    pdf.para(
        f"Certification requires a HAI Score of at least {_num(threshold, 0)}, evidence confidence of at least "
        f"{_num(min_conf, 0)}%, admissible evidence in every pillar and a named reviewer's signature.",
        8.8,
    )
    if cert:
        tone = GREEN if cert["decision"] == CertificationOutcome.CERTIFIED.value else RED
        pdf.kv(
            [
                ("Decision", cert["decision_label"]),
                ("Certificate number", _s(cert.get("certificate_number"))),
                ("Reviewer", _s(cert.get("reviewer_id"))),
                ("Signed", _date(cert.get("signed_at"))),
                ("Valid until", _date(cert.get("expires_at"))),
                ("Threshold applied", _num(cert.get("threshold_applied"), 0)),
            ],
            key_width=46,
            size=9,
        )
        if cert.get("gate_reasons"):
            pdf.para("Reasons: " + "; ".join(cert["gate_reasons"]), 8.6, tone)
    elif result and result.get("gate_reasons"):
        pdf.para("Not yet eligible: " + "; ".join(result["gate_reasons"]) + ".", 8.8, RED)
    else:
        pdf.para("No certification decision has been signed for this assessment version.", 8.8, GREY)

    pdf.h2("Reproducibility")
    a = r.get("assessment", {})
    versions = a.get("versions", {})
    snap = r.get("snapshot") or {}
    pdf.kv(
        [
            ("Assessment", _s(a.get("id"))),
            (
                "Snapshot",
                f"{_s(snap.get('id'))} frozen {_date(snap.get('frozen_at'))}, {snap.get('links', 0)} links"
                if snap
                else "not frozen yet",
            ),
            ("Snapshot SHA-256", _s(snap.get("sha256"))),
            ("Result SHA-256", _s((result or {}).get("result_sha256"))),
            ("Ontology / methodology", f"{_s(versions.get('ontology'))} / {_s(versions.get('methodology'))}"),
            (
                "Ruleset / prompt / model",
                f"{_s(versions.get('ruleset'))} / {_s(versions.get('prompt'))} / {_s(versions.get('model'))}",
            ),
        ],
        key_width=46,
        size=8.4,
    )
    if r.get("drafts_notice"):
        pdf.para(str(r["drafts_notice"]), 7.8, MUTED, "I")


def _gaps_page(pdf: ReportPDF, r: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.h1("Where Evidence Is Missing")
    pdf.para(
        "A factual list of what public evidence did not show, by pillar and focus area. It is not a judgement "
        "that a practice is absent; it marks what has not yet been made publicly verifiable. Remediation "
        "guidance is Humaital's and is issued separately.",
        9,
        GREY,
    )
    pillars = {p["code"]: p["name"] for p in r.get("pillars", [])}
    for code, name in pillars.items():
        gaps = _pillar_gaps([c for c in r.get("criteria", []) if c.get("pillar") == code])
        pdf.h3(name)
        if gaps:
            pdf.bullets(gaps, 8.6)
        else:
            pdf.para("Every criterion reaches independent verification or is outside scope.", 8.6, GREEN)
    pdf.h2("Focus Areas Without Evidence")
    missing = [fa for fa in r.get("focus_areas", []) if not fa.get("links")]
    if missing:
        pdf.bullets([f"{fa['label']}: {_clip(fa.get('question', ''), 140)}" for fa in missing], 8.6)
    else:
        pdf.para("Every focus area has at least one admissible supporting quote.", 8.6, GREEN)
    notes = r.get("execution_notes", [])
    if notes:
        pdf.h2("Execution Notes")
        pdf.para(str(notes[0].get("note", "")), 8.6, GREY)
        pdf.bullets([f"{n['name']} ({n['code']})" for n in notes], 8.4)


def _appendix(pdf: ReportPDF, r: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.h1("Evidence Appendix")
    pdf.para(
        "A traceable record of every source collected and the evidence identified in it. Sources with no evidence "
        "are listed as gap indicators. Each quote is the exact span stored in the snapshot.",
        9,
        GREY,
    )
    links_by_doc: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for c in r.get("criteria", []):
        for link in c.get("evidence", []):
            links_by_doc.setdefault(str(link.get("document_id")), []).append((c, link))
    sources = r.get("sources", [])
    seen: set[str] = set()
    for s in sources:
        sid = str(s.get("id"))
        seen.add(sid)
        _source_block(pdf, s, links_by_doc.get(sid, []))
    orphans = [(doc, links) for doc, links in links_by_doc.items() if doc not in seen]
    for doc, links in orphans:
        first = links[0][1]
        _source_block(
            pdf,
            {
                "id": doc,
                "canonical_url": first.get("canonical_url"),
                "title": first.get("document_title"),
                "publisher": first.get("publisher_name"),
                "publisher_type": first.get("publisher_type"),
                "published_at": first.get("published_at"),
            },
            links,
        )
    if not sources and not orphans:
        pdf.para("No source has been collected yet.", 8.8, MUTED, "I")
    pdf.ln(4)
    pdf.para(CLOSING_NOTE.format(long_name=r["product"]["long_name"]), 7.8, MUTED, "I")


def _source_block(pdf: ReportPDF, s: dict[str, Any], links: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
    pdf.ensure(26)
    pdf.rule(2)
    pdf.font(9.5, DARK, "B")
    pdf.multi_cell(
        0, 5.5, _clip(s.get("title") or s.get("canonical_url") or s.get("id"), 120), new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    pdf.font(7.8, GREY)
    meta = [
        f"Publisher: {_s(s.get('publisher'))} ({_label('publisher_type', s.get('publisher_type'))})",
        f"Published: {_date(s.get('published_at'))}",
    ]
    if s.get("connector"):
        meta.append(f"Connector: {s['connector']}")
    pdf.cell(0, 4.4, "   ".join(meta), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if s.get("canonical_url"):
        pdf.font(7.8, BLUE)
        pdf.multi_cell(
            0, 4.4, str(s["canonical_url"]), new_x=XPos.LMARGIN, new_y=YPos.NEXT, link=str(s["canonical_url"])
        )
    supporting = [x for x in links if _is_support(x[1])]
    if not links:
        pdf.font(8.2, AMBER, "B")
        pdf.cell(
            0,
            5,
            "Gap indicator: collected, no evidence identified in this source.",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        return
    pdf.font(8.2, DARK, "B")
    pdf.cell(
        0,
        5,
        f"Evidence identified: {len(links)} link{'s' if len(links) != 1 else ''}, {len(supporting)} admissible "
        "and supporting",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    for c, link in sorted(links, key=lambda x: (0 if _is_support(x[1]) else 1, str(x[0]["code"]))):
        pdf.ensure(12)
        role = _label("polarity", link.get("polarity"))
        admissible = link.get("admissibility") == Admissibility.ADMISSIBLE.value
        tone = GREEN if admissible and link.get("polarity") == Polarity.SUPPORTS.value else RED if admissible else MUTED
        pdf.font(7.8, tone, "B")
        pdf.cell(
            0,
            4.4,
            f"{c['code']} {c['name']}  |  {_label('maturity_rung', link.get('maturity_rung'))}  |  {role}  |  "
            f"{_label('admissibility', link.get('admissibility'))}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.font(8, BODY)
        pdf.set_x(pdf.l_margin + 4)
        pdf.multi_cell(pdf.epw - 4, 4.4, "“" + _clip(link.get("quote"), 420) + "”", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(0.8)


def build_pdf(
    report: dict[str, Any],
    *,
    website: str = "humanalignmentindex.com",
    tagline: str = "Where Humanity Leads Technology",
) -> ReportPDF:
    pdf = ReportPDF(report, website, tagline)
    _cover(pdf, report)
    _how_evaluated(pdf, report)
    _snapshot(pdf, report)
    _pillar_pages(pdf, report)
    _verification_page(pdf, report)
    _evidence_page(pdf, report)
    _gaps_page(pdf, report)
    _appendix(pdf, report)
    return pdf


def render_report_pdf(
    report: dict[str, Any],
    *,
    website: str = "humanalignmentindex.com",
    tagline: str = "Where Humanity Leads Technology",
) -> bytes:
    """The report as PDF bytes."""
    return bytes(build_pdf(report, website=website, tagline=tagline).output())
