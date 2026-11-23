"""Render docs/hai-core-engine-and-ontology.pdf: the Core Engine and the Ontology in plain terms.

A four-page, non-technical guide to how the Core Engine works with the Ontology and how the HAI
Score is calculated. Every count, weight and threshold printed in it is read from the manifest
under ``ontology/`` and the worked example is computed by the engine's own scoring function, so
the guide cannot drift from the platform. The prose is written here. Rerun after a methodology
change:

    make engine-guide
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import TableBordersLayout, TableCellFillMode, XPos, YPos
from fpdf.fonts import FontFace

import hai_engine
from hai_core.generated.enums import ATTRIBUTES, LABELS, CoverageState, MaturityRung, SourceTier
from hai_engine.rules.context import CriterionState
from hai_engine.scoring import aggregate, criterion_ratio
from hai_ontology.loader import find_repo_root, load_manifest
from hai_ontology.meta import CriterionDef, Manifest

REPO = find_repo_root(Path(__file__))
OUTPUT = REPO / "docs" / "hai-core-engine-and-ontology.pdf"
ASSETS = Path(hai_engine.__file__).parent / "assets"
FONTS = ASSETS / "fonts"
LOGO = ASSETS / "humaital-logo.png"

Rgb = tuple[int, int, int]
RED: Rgb = (199, 53, 66)
DARK: Rgb = (31, 41, 51)
BODY: Rgb = (55, 65, 81)
GREY: Rgb = (107, 114, 128)
LINE: Rgb = (222, 226, 230)
PANEL: Rgb = (246, 247, 249)
PANEL_RED: Rgb = (253, 243, 244)
PANEL_AMBER: Rgb = (255, 249, 230)
AMBER: Rgb = (176, 108, 0)
WHITE: Rgb = (255, 255, 255)

STEPS: list[tuple[str, str]] = [
    (
        "Collect",
        "The platform reads the organization's website, reports, public filings and other sources. "
        "Every source is recorded, including the ones that refuse access.",
    ),
    ("Link", "The text is cut into quoted passages. A passage that speaks to one of the criteria is linked to it."),
    ("Classify", "Each link is graded: is this a promise, a described control, or a record that something was done?"),
    ("Freeze", "The evidence and its grades are sealed. From here on nothing can be added or altered."),
    ("Evaluate", "Optionally, an AI assistant reads the sealed evidence and suggests a level for each criterion."),
    ("Decide", "The Core Engine applies the rules in order and writes the levels, the scores and the reasons."),
    ("Review", "A human reviewer handles anything the rules flagged and signs any certification."),
]

# The ladder in everyday words, keyed by the rung each level requires.
PLAIN_RUNG: dict[str, str] = {
    MaturityRung.NONE.value: "Nothing relevant was found.",
    MaturityRung.STATED_COMMITMENT.value: "The organization says it does this.",
    MaturityRung.SPECIFIED_CONTROL.value: "It describes who is responsible and how it is done.",
    MaturityRung.DOCUMENTED_EXECUTION.value: "It shows dated or counted records that it was done.",
    MaturityRung.INDEPENDENTLY_VERIFIED.value: "An independent party or a regulator confirms it.",
}

# Level and part of the next level for the invented organization, pillar by pillar in manifest order.
EXAMPLE_LEVELS: dict[str, list[tuple[int, float]]] = {
    "TRU": [(3, 0.5), (3, 0.0), (3, 0.5), (3, 0.0)],
    "ACC": [(4, 0.0), (3, 0.0), (3, 0.5)],
    "PUR": [(3, 0.5), (3, 0.0), (2, 0.5)],
    "SAF": [(4, 0.0), (3, 0.5), (3, 0.0)],
    "TRN": [(3, 0.5), (3, 0.0), (2, 0.0)],
    "IMP": [(3, 0.0), (3, 0.0), (2, 0.0), (1, 0.0)],
}
EXAMPLE_PILLAR = "SAF"


def num(value: float, digits: int = 1) -> str:
    """A number without trailing zeros: 0.5, 3, 62.5."""
    text = f"{value:.{max(digits, 2)}f}".rstrip("0").rstrip(".")
    return text or "0"


class Guide(FPDF):
    """A4 portrait in the house style of the HAI Score report."""

    def __init__(self, footer_text: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.footer_text = footer_text
        self.set_margins(18, 24, 18)
        self.set_auto_page_break(auto=True, margin=17)
        self.add_font("Sans", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("Sans", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.alias_nb_pages()
        self.set_title("How The HAI Score Is Produced: The Core Engine And The Ontology In Plain Terms")
        self.set_author("Humaital")
        self.set_creator("HAI Score platform")
        self.section = 0

    # ----------------------------------------------------------------- chrome
    def header(self) -> None:
        if LOGO.exists():
            self.image(str(LOGO), x=self.l_margin, y=8, h=9)
        self.set_draw_color(*RED)
        self.set_line_width(0.5)
        self.line(self.l_margin, 19, self.w - self.r_margin, 19)
        self.set_y(23)

    def footer(self) -> None:
        self.set_y(-12)
        self.font(7.3, GREY)
        self.cell(0, 5, self.footer_text, align="L")
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    # ----------------------------------------------------------------- text
    def font(self, size: float, color: Rgb = BODY, style: str = "") -> None:
        self.set_font("Sans", style, size)
        self.set_text_color(*color)

    def ensure(self, height: float) -> None:
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def h1(self, text: str) -> None:
        self.section += 1
        self.ensure(30)
        self.ln(1.5)
        self.font(12.5, DARK, "B")
        self.cell(0, 7.5, f"{self.section}. {text}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*LINE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def h2(self, text: str) -> None:
        self.ensure(16)
        self.font(9.6, RED, "B")
        self.cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text: str, size: float = 9.0, color: Rgb = BODY, gap: float = 1.8) -> None:
        self.font(size, color)
        self.multi_cell(0, size * 0.52, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(gap)

    def bullets(self, items: list[tuple[str, str]], size: float = 9.0) -> None:
        """Items with a bold lead-in: ("One source of truth.", "The database ...")."""
        line_h = size * 0.52
        for lead, text in items:
            self.ensure(line_h * 2 + 1)
            y = self.get_y()
            self.set_fill_color(*RED)
            self.ellipse(self.l_margin + 1.2, y + line_h / 2 - 0.6, 1.2, 1.2, style="F")
            self.set_x(self.l_margin + 5)
            self.font(size, BODY)
            markdown = f"**{lead}** {text}" if lead else text
            self.multi_cell(self.epw - 5, line_h, markdown, markdown=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(0.7)
        self.ln(1.0)

    def _line_count(self, width: float, line_h: float, text: str) -> int:
        lines = self.multi_cell(width, line_h, text, dry_run=True, output="LINES")
        return len(lines) if isinstance(lines, list) else 1

    def box(self, title: str, lines: list[str], fill: Rgb = PANEL, accent: Rgb = DARK, bold: bool = False) -> None:
        """A boxed block: a formula, a note or a caution."""
        line_h = 4.5
        style = "B" if bold else ""
        self.font(8.8, style=style)
        counts = [self._line_count(self.epw - 10, line_h, t) for t in lines]
        height = (6.8 if title else 2.4) + sum(count * line_h + 1.0 for count in counts) + 1.6
        self.ensure(height + 2)
        x, y = self.l_margin, self.get_y()
        self.set_fill_color(*fill)
        self.rect(x, y, self.epw, height, style="F")
        self.set_fill_color(*accent)
        self.rect(x, y, 1.1, height, style="F")
        self.set_xy(x + 5, y + 2.2)
        if title:
            self.font(7.8, accent, "B")
            self.cell(0, 4.2, title.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_x(x + 5)
        for text in lines:
            self.font(8.8, DARK if bold else BODY, style)
            self.multi_cell(self.epw - 10, line_h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_xy(x + 5, self.get_y() + 1.0)
        self.set_xy(self.l_margin, y + height + 2.6)

    def formula(self, lines: list[str]) -> None:
        self.box("", lines, fill=PANEL, accent=RED, bold=True)

    def grid(
        self,
        headings: list[str],
        rows: list[list[str]],
        widths: list[float],
        align: list[str] | None = None,
        size: float = 8.2,
        last_bold: bool = False,
    ) -> None:
        self.ensure(16)
        self.font(size)
        head = FontFace(emphasis="BOLD", color=WHITE, fill_color=DARK, size_pt=size)
        strong = FontFace(emphasis="BOLD", color=DARK, size_pt=size)
        scale = self.epw / sum(widths)
        # The table restores the graphics state after its heading row; without this the striped rows
        # would take whatever fill colour was last drawn (a red accent bar, for example).
        self.set_fill_color(*PANEL)
        with self.table(
            col_widths=tuple(w * scale for w in widths),
            text_align=tuple(align or ["LEFT"] * len(widths)),
            borders_layout=TableBordersLayout.HORIZONTAL_LINES,
            cell_fill_color=PANEL,
            cell_fill_mode=TableCellFillMode.ROWS,
            headings_style=head,
            line_height=size * 0.54,
            padding=(1.2, 1.8),
        ) as table:
            row = table.row()
            for heading in headings:
                row.cell(heading)
            for position, values in enumerate(rows):
                row = table.row()
                whole = last_bold and position == len(rows) - 1
                for index, value in enumerate(values):
                    row.cell(value, style=strong if index == 0 or whole else None)
        self.ln(2.8)

    # ----------------------------------------------------------------- figures
    def _node(self, x: float, y: float, w: float, h: float, title: str, caption: str, strong: bool = False) -> None:
        self.set_fill_color(*(RED if strong else PANEL))
        self.set_draw_color(*(RED if strong else LINE))
        self.set_line_width(0.3)
        self.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=1.8)
        self.font(9.4, WHITE if strong else DARK, "B")
        self.set_xy(x, y + 2.0)
        self.cell(w, 5, title, align="C")
        self.font(7.6, WHITE if strong else GREY)
        self.set_xy(x + 2, y + 7.4)
        self.multi_cell(w - 4, 3.6, caption, align="C")

    def _arrow(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.set_draw_color(*GREY)
        self.set_fill_color(*GREY)
        self.set_line_width(0.45)
        if abs(y2 - y1) < 0.01:
            self.line(x1, y1, x2 - 2, y2)
            self.polygon([(x2 - 2.2, y2 - 1.4), (x2, y2), (x2 - 2.2, y2 + 1.4)], style="F")
        else:
            self.line(x1, y1, x2, y2 - 2)
            self.polygon([(x2 - 1.4, y2 - 2.2), (x2, y2), (x2 + 1.4, y2 - 2.2)], style="F")

    def relationship(self) -> None:
        """The rulebook above the referee; evidence in from the left, the result out to the right."""
        box_w, box_h, gap = 50.0, 15.5, (self.epw - 150.0) / 2
        self.ensure(box_h * 2 + 10)
        top = self.get_y()
        row = top + box_h + 5
        left = self.l_margin
        middle = left + box_w + gap
        right = middle + box_w + gap
        self._node(middle, top, box_w, box_h, "The Ontology", "The rulebook: questions, words, weights and rules")
        self._node(left, row, box_w, box_h, "Sealed Evidence", "Quoted passages from real documents")
        self._node(middle, row, box_w, box_h, "The Core Engine", "The referee: applies the rulebook", strong=True)
        self._node(right, row, box_w, box_h, "The Result", "Levels, score, confidence, outcome and the reasons")
        self._arrow(middle + box_w / 2, top + box_h, middle + box_w / 2, row)
        self._arrow(left + box_w, row + box_h / 2, middle, row + box_h / 2)
        self._arrow(middle + box_w, row + box_h / 2, right, row + box_h / 2)
        self.set_xy(self.l_margin, row + box_h + 3)

    def pipeline(self) -> None:
        """The seven steps in a row, numbered, with an arrow between each pair."""
        count = len(STEPS)
        gap = 3.2
        width = (self.epw - gap * (count - 1)) / count
        height = 12.5
        self.ensure(height + 6)
        y = self.get_y() + 0.5
        for index, (name, _) in enumerate(STEPS):
            x = self.l_margin + index * (width + gap)
            decided = name == "Decide"
            self.set_fill_color(*(RED if decided else PANEL))
            self.set_draw_color(*(RED if decided else LINE))
            self.set_line_width(0.3)
            self.rect(x, y, width, height, style="DF", round_corners=True, corner_radius=1.6)
            self.font(6.6, WHITE if decided else GREY, "B")
            self.set_xy(x, y + 1.6)
            self.cell(width, 3.3, f"STEP {index + 1}", align="C")
            self.font(8.8, WHITE if decided else DARK, "B")
            self.set_xy(x, y + 5.8)
            self.cell(width, 4.6, name, align="C")
            if index < count - 1:
                ax, ay = x + width + 0.5, y + height / 2
                self.set_fill_color(*GREY)
                self.polygon([(ax, ay - 1.3), (ax + gap - 1, ay), (ax, ay + 1.3)], style="F")
        self.set_xy(self.l_margin, y + height + 3)


def assessment_example(manifest: Manifest) -> dict[str, Any]:
    """Twenty criterion states for an invented organization, aggregated by the engine's own scoring function."""
    states: list[tuple[CriterionDef, CriterionState]] = []
    seen: dict[str, int] = {}
    floor = manifest.methodology.scoring.missing_level
    for criterion in manifest.criteria:
        position = seen.get(criterion.pillar, 0)
        seen[criterion.pillar] = position + 1
        level, progress = EXAMPLE_LEVELS[criterion.pillar][position]
        coverage = CoverageState.MISSING if level == floor else CoverageState.OBSERVED
        states.append((criterion, CriterionState(level=level, level_progress=progress, coverage_state=coverage.value)))
    result = aggregate(manifest.methodology, list(manifest.pillars), states, stage_band="mature")
    return {"states": states, "result": result}


def build(output: Path, as_of: date) -> Path:
    manifest = load_manifest(REPO / "ontology")
    md = manifest.methodology
    scoring = md.scoring
    rules = manifest.ruleset.rules
    criteria = manifest.criteria
    pillars = manifest.pillars
    rung_label = LABELS["maturity_rung"]
    levels = sorted(criteria[0].levels, key=lambda lv: lv.level)
    span = scoring.level_max - scoring.level_min
    ai_rule = scoring.ai_specific
    early_credit = scoring.stage_expectations.credit("early")
    comps = md.confidence.components
    cert = md.certification
    weights = [c.materiality_weight for c in criteria]
    stamp = (
        f"Ontology {manifest.ontology_version}, methodology {manifest.methodology_version} ({md.status}), "
        f"ruleset {manifest.ruleset.version}"
    )
    pdf = Guide(f"How the HAI Score is produced  |  {stamp}  |  generated {as_of.isoformat()}")

    # ------------------------------------------------------------------ title
    pdf.add_page()
    pdf.ln(1)
    pdf.font(8.4, RED, "B")
    pdf.cell(0, 4.5, "A PLAIN-LANGUAGE GUIDE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.font(19, DARK, "B")
    pdf.cell(0, 10, "How The HAI Score Is Produced", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.font(11, GREY)
    pdf.cell(0, 6, "The Core Engine, The Ontology And The Calculation", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.para(
        "The HAI Score platform reads what an organization publishes about how it governs AI and turns it into a "
        f"score out of {num(scoring.score_scale)}, with the reasons attached. Two parts make that possible. The "
        "Ontology is the rulebook: it says what counts as evidence, what the questions are and how the answers "
        "are weighed. The Core Engine is the referee: it applies the rulebook to the evidence, the same way every "
        "time. This guide explains both, and how the score is worked out, without assuming any technical "
        "background."
    )

    # ------------------------------------------------------------------ 1
    pdf.h1("The Ontology: The Rulebook")
    pdf.para(
        '"Ontology" is a formal word for a written description of a subject: the things in it, the words used '
        "for them and the rules that connect them. Ours is a set of plain text files that people can read, "
        "review and approve. It holds four kinds of content."
    )
    pdf.bullets(
        [
            (
                "The things.",
                f"The {len(manifest.entities)} kinds of record the platform keeps, such as an "
                "organization, a document, a quoted passage, a decision and a certificate.",
            ),
            (
                "The words.",
                f"{len(manifest.vocabularies)} fixed lists of allowed terms, so that a phrase such as "
                f'"{rung_label[MaturityRung.SPECIFIED_CONTROL.value].lower()}" or '
                f'"{LABELS["outcome_status"]["access_limited"].lower()}" means one thing everywhere.',
            ),
            (
                "The methodology.",
                f"The {len(pillars)} pillars, the {len(criteria)} criteria (the questions asked "
                "about every organization), how much each one weighs and the thresholds for certification.",
            ),
            (
                "The rules.",
                f"{len(rules)} rules, in a fixed order, that turn evidence into levels, a score and an outcome.",
            ),
        ]
    )
    pdf.h2("Why It Is Kept Separate From The Software")
    pdf.bullets(
        [
            (
                "One source of truth.",
                "The database, the software's vocabulary, the labels on the screens and the "
                "reference documents are generated from the rulebook. Nobody retypes a criterion or a threshold "
                "somewhere else, so they cannot drift apart.",
            ),
            (
                "Changes are deliberate.",
                "Changing the methodology means editing the rulebook, not rewriting "
                "software. Every change gets a new version number and a written record of what changed and why.",
            ),
            (
                "Every score names its rulebook.",
                "Each result records the version that produced it. An old score "
                "is never quietly recalculated under new rules.",
            ),
        ]
    )

    # ------------------------------------------------------------------ 2
    pdf.h1("The Core Engine: The Referee")
    pdf.para(
        "The Core Engine is the part of the platform that decides. It receives two things: the rulebook and a "
        f"sealed copy of the evidence collected for one organization. It returns a level for each of the "
        f"{len(criteria)} criteria, a score for each pillar, the HAI Score, a confidence figure, an outcome, and "
        "a step-by-step record of why."
    )
    pdf.relationship()
    pdf.bullets(
        [
            (
                "Evidence only.",
                "Nothing reaches a score unless a quoted passage from a real document supports "
                "it. Reputation, size and industry play no part.",
            ),
            (
                "Same input, same answer.",
                "The engine looks only at the sealed evidence and the rulebook. It does "
                "not browse the web, ask an AI model or check the date, so a rerun gives exactly the same result.",
            ),
            (
                "People sign.",
                "An AI assistant may suggest a level. The rules can lower a suggestion and can "
                "never raise a level above what the evidence supports. Only a named human reviewer can sign a "
                "certification.",
            ),
        ]
    )

    # ------------------------------------------------------------------ 3
    pdf.h1("From A Web Page To A Decision")
    pdf.para("Every assessment goes through the same seven steps. The Core Engine is step six.", gap=1.2)
    pdf.pipeline()
    pdf.grid(
        ["Step", "What Happens"],
        [[f"{index}. {name}", text] for index, (name, text) in enumerate(STEPS, start=1)],
        [26, 148],
    )

    # ------------------------------------------------------------------ 4
    pdf.h1("How Strong Is The Evidence: The Ladder")
    pdf.para(
        "For each criterion the engine asks one question: how far up this ladder does the evidence reach? The "
        "step reached is the level, and the level sets the points."
    )
    pdf.grid(
        ["Level", "Evidence Found", "In Plain Terms", f"Points Of {num(scoring.score_scale)}"],
        [
            [
                str(lv.level),
                rung_label[lv.required_maturity_rung],
                PLAIN_RUNG[lv.required_maturity_rung],
                num(criterion_ratio(lv.level, md) * scoring.score_scale),
            ]
            for lv in levels
        ],
        [14, 42, 92, 26],
        align=["LEFT", "LEFT", "LEFT", "RIGHT"],
    )
    needed = scoring.corroboration.min_passages
    corroborated = " and ".join(str(lv.level) for lv in levels if lv.required_maturity_rung in needed)
    two = num(float(max(needed.values()))) if needed else "1"
    control = next(lv.level for lv in levels if lv.required_maturity_rung == MaturityRung.SPECIFIED_CONTROL.value)
    plus_levels = " and ".join(str(lv.level) for lv in levels if lv.required_maturity_rung in ai_rule.rungs)
    pdf.h2("The Safeguards")
    pdf.bullets(
        [
            (
                "Quotes must be real.",
                "A quoted passage must match the stored document word for word, or it cannot be used.",
            ),
            (
                "One sentence is not enough.",
                f"Levels {corroborated} need {two} separate passages, because a "
                "single sentence can sound right by accident.",
            ),
            (
                "It has to be about AI.",
                "Ordinary company governance, such as a board committee or a code of "
                f"conduct, can earn up to level {control}. Anything higher must be a record about AI itself.",
            ),
            (
                "Half steps.",
                f"At levels {plus_levels}, when at least {ai_rule.min_passages} of the passages are "
                f"specifically about AI, the criterion earns {num(ai_rule.level_progress)} of a level more. An "
                "early-stage organization earns "
                f"{num(early_credit)} of a level on each criterion it has evidence for, because formal controls "
                f"are not yet expected of it. A control about AI is therefore level "
                f"{num(control + ai_rule.level_progress)}, worth "
                f"{num(criterion_ratio(control, md, ai_rule.level_progress) * scoring.score_scale)} points.",
            ),
            (
                "Not reached is not the same as not done.",
                "When sources could not be read, the criterion is left "
                "out instead of being scored at the bottom. When "
                f"{num(md.outcome.access_limited_unavailable_share * 100)} percent or more of the criteria are "
                "left out, no overall score is published.",
            ),
        ]
    )

    # ------------------------------------------------------------------ 5
    pdf.h1("How The Score Is Calculated")
    pdf.para("Three steps turn the levels into the HAI Score. There is no multiplier and no adjustment afterwards.")
    pdf.bullets(
        [
            (
                "Step 1: each level becomes points.",
                f"Level {scoring.level_min} is 0 points and level "
                f"{scoring.level_max} is {num(scoring.score_scale)}; each level in between adds "
                f"{num(scoring.score_scale / span)}.",
            ),
            (
                "Step 2: each pillar is a weighted average of its criteria.",
                f"Criteria that matter more weigh more (from {num(min(weights))} to {num(max(weights))}).",
            ),
            (
                "Step 3: the HAI Score is a weighted average of the pillars.",
                f"The pillar weights are the points each pillar carries out of {num(scoring.score_scale)}.",
            ),
        ]
    )
    pdf.formula(
        [
            f"points = (level - {scoring.level_min}) / {span} x {num(scoring.score_scale)}",
            "pillar score = sum(points x weight) / sum(weight)",
            "HAI Score = sum(pillar weight x pillar score) / sum(pillar weight)",
        ]
    )
    example = assessment_example(manifest)
    result = example["result"]
    shown = next(p for p in pillars if p.code == EXAMPLE_PILLAR)
    in_pillar = [(c, s) for c, s in example["states"] if c.pillar == shown.code]
    pdf.h2(f"An Example: The {shown.name} Pillar Of An Invented Organization")
    pdf.grid(
        ["Criterion", "What Was Found", "Level", "Points", "Weight"],
        [
            [
                c.name,
                "Records of AI practice"
                if s.level >= 4
                else ("A control about AI" if s.level_progress else "A general control"),
                num(s.level + s.level_progress),
                num(criterion_ratio(s.level, md, s.level_progress) * scoring.score_scale),
                num(c.weight * c.materiality_weight),
            ]
            for c, s in in_pillar
        ],
        [58, 50, 20, 22, 24],
        align=["LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"],
    )
    top = " + ".join(
        f"{num(criterion_ratio(s.level, md, s.level_progress) * scoring.score_scale)} x "
        f"{num(c.weight * c.materiality_weight)}"
        for c, s in in_pillar
    )
    bottom = " + ".join(num(c.weight * c.materiality_weight) for c, _ in in_pillar)
    shown_score = next(p.score for p in result.pillars if p.code == shown.code)
    pdf.formula([f"{shown.name} = ({top}) / ({bottom}) = {num(shown_score)}"])
    pdf.para(
        "The same is done for every pillar, and the six pillar scores are combined by their weights. All figures "
        "below were computed by the engine itself.",
        gap=1.4,
    )
    pillar_rows = [
        [
            next(x.name for x in pillars if x.code == p.code),
            num(p.weight * scoring.score_scale),
            num(p.score),
            num(p.weight * p.score, 2),
        ]
        for p in result.pillars
    ]
    pillar_rows.append(
        [
            "HAI Score",
            num(sum(p.weight for p in result.pillars) * scoring.score_scale),
            "",
            num(result.hai_score or 0.0),
        ]
    )
    pdf.grid(
        ["Pillar", f"Weight (Points Of {num(scoring.score_scale)})", "Pillar Score", "Contribution To The Score"],
        pillar_rows,
        [56, 40, 32, 46],
        align=["LEFT", "RIGHT", "RIGHT", "RIGHT"],
        last_bold=True,
    )

    # ------------------------------------------------------------------ 6
    pdf.add_page()
    pdf.h1("Confidence: How Sure Are We")
    pdf.para(
        "The score says how mature the evidenced governance is. Confidence is a separate figure, from 0 to 100, "
        "that says how solid the evidence behind the score is. It never changes a level. It has four ingredients."
    )
    pdf.grid(
        ["Ingredient", "Share", "The Question It Answers"],
        [
            [
                "Who published it",
                f"{num(comps.source_credibility * 100)} percent",
                "A regulator's record counts most, the organization's own site less, social media least.",
            ],
            [
                "What kind of evidence",
                f"{num(comps.evidence_type * 100)} percent",
                "Records of action count more than descriptions, and descriptions more than promises.",
            ],
            [
                "How many sources agree",
                f"{num(comps.cross_source_validation * 100)} percent",
                f"One source earns nothing here; {comps.cross_source_full_at} or more separate sources earn the "
                "full share.",
            ],
            [
                "How recent it is",
                f"{num(comps.recency * 100)} percent",
                "Evidence counts for less as it ages. A news report fades faster than a regulator's record.",
            ],
        ],
        [42, 24, 108],
    )
    own_site = 100 * (
        comps.source_credibility * float(ATTRIBUTES["source_tier"][SourceTier.T3.value]["weight"])
        + comps.evidence_type * comps.evidence_type_credit[MaturityRung.DOCUMENTED_EXECUTION.value]
        + comps.recency
    )
    pdf.box(
        "Why Confidence Is Often Low",
        [
            "An organization evidenced only by its own website is a single source. Even with fresh, dated records "
            f"its confidence cannot pass {num(own_site)}, because nothing independent confirms what it says. "
            f"Certification needs {num(cert.min_confidence)}. That is by design: a published claim is a start, "
            "and independent or submitted evidence is what makes it certifiable.",
        ],
    )

    # ------------------------------------------------------------------ 7
    pdf.h1("Review, Certification And Outcome")
    by_stage: dict[float, list[str]] = {}
    for entry in cert.stage_size_table.rows:
        names = by_stage.setdefault(entry.threshold, [])
        label = LABELS["stage_band"][entry.stage_band].lower()
        if label not in names:
            names.append(label)
    thresholds = "; ".join(f"{num(value)} for {' and '.join(names)}" for value, names in sorted(by_stage.items()))
    outcomes = [v.label for v in sorted(manifest.vocabulary("outcome_status").values, key=lambda v: v.rank or 0)]
    pdf.bullets(
        [
            (
                "When a person is brought in.",
                "Conflicting evidence, a reported incident, borderline confidence "
                "or a request for certification sends the assessment to a human reviewer. The reviewer acts with a "
                "written reason, and the engine runs again with that decision applied.",
            ),
            (
                "What certification requires.",
                f"A score at or above the threshold ({thresholds}), confidence of "
                f"at least {num(cert.min_confidence)}, evidence in every pillar, no open review item, and the "
                f"signature of a named reviewer. A certificate is valid for {cert.validity_months} months.",
            ),
            ("The outcome.", "Every assessment ends with exactly one of: " + ", ".join(outcomes) + "."),
        ]
    )

    # ------------------------------------------------------------------ 8
    pdf.h1("Why The Result Can Be Trusted")
    pdf.bullets(
        [
            (
                "Every decision shows its work.",
                "Each criterion lists the rules that ran, in order, and the quoted passages behind the level.",
            ),
            (
                "It can be replayed.",
                "The sealed evidence and the rulebook version are kept. Running the engine "
                "on them again must reproduce the result exactly, and an automatic test checks this.",
            ),
            (
                "Nothing is overwritten.",
                "A correction adds a new record that replaces the old one in view. The "
                "history stays, and the audit log can be verified.",
            ),
        ]
    )
    pdf.box(
        "Draft Status",
        [
            f"Methodology {manifest.methodology_version} is {md.status}. Humaital owns the {len(criteria)} "
            "criteria, their level descriptions and the weights. The criterion wording, some weights, the half "
            "steps and the confidence details are placeholders or calibration choices that await Humaital's "
            "approval. Every number in this guide was read from the rulebook when the guide was generated.",
        ],
        fill=PANEL_AMBER,
        accent=AMBER,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--date", default=date.today().isoformat(), help="the generation date printed in the footer")
    args = parser.parse_args()
    build(Path(args.output), date.fromisoformat(args.date))


if __name__ == "__main__":
    main()
