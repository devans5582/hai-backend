# 0017 PDF Report Export

Status: accepted (2026-11-09).

## Context

Participating organizations and reviewers need a file they can send, file and
sign off, not only a console page. Humaital's published HAI Report (Rubric v2,
Microsoft, 2026-05-29) sets the expected shape: a cover with the score,
confidence and outcome, a page on how the organization was evaluated, an
alignment snapshot, an analysis page per pillar, an evidence and certification
page and an evidence appendix. The platform's report has since grown the
evidence ladder, focus-area coverage, control verification, incident timelines,
impact measures and the confidence components (ADR 0016), and the published
report's playbook and key actions are methodology content that only Humaital
may write.

## Decisions

1. The PDF is rendered server side by the engine (`hai_engine.report_pdf`)
   from the same dictionary the JSON report returns, so both carry identical
   stored values. The console never renders or computes a report; its export
   buttons download the file with the signed-in credentials.
2. fpdf2 with DejaVu Sans embedded (Bitstream Vera licence, in
   `hai_engine/assets/fonts`) so quotes in any script render. No system
   packages are needed in the image.
3. The layout follows the published report and adds the 2.0.0 content: the
   evidence ladder, focus areas, verification of controls, containment tests,
   autonomy and monitoring, incident response timelines, impact measures, the
   confidence components, and the reproducibility identifiers (assessment,
   snapshot hash, result hash, version pins).
4. No remediation advice is generated. The "Where evidence is missing" page and
   the per-criterion gap lines state facts only: no admissible evidence, the
   highest rung reached and the rungs not evidenced, focus areas without
   evidence. Key actions, priority actions and the 90-day plan of the published
   report are Humaital's and are left out until Humaital supplies them
   (`TODO(humaital)`).
5. The report dictionary gains `version` (this assessment's number among the
   organization's assessments), `certification` (the current signed decision),
   `benchmark` (peers with the same industry, stage and size), `scale` and the
   vocabulary definitions the PDF prints. These are additive.
6. Two endpoints: `GET /v1/assessments/{id}/report.pdf` for one version and
   `GET /v1/organizations/{org_id}/report.pdf` for the latest version. Both
   apply the same visibility rules as the JSON report. The footer website and
   tagline are settings (`HAI_REPORT_WEBSITE`, `HAI_REPORT_TAGLINE`).

## Consequences

* The engine package carries about 2 MB of font files; fpdf2 subsets them so
  a report is a few hundred kilobytes.
* A change to the report dictionary must keep `test_report_pdf.py` rendering;
  the fixture there mirrors the console's.
* When Humaital supplies playbook content it belongs in the methodology
  manifest, not in the renderer.
