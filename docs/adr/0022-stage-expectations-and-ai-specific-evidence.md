# Stage Expectations And AI-Specific Evidence

Date: 2026-11-23

Status: Accepted implementation; methodology content remains draft.

## Request And Evidence

After ADR 0021 the owner asked again for the scores to be recalibrated until
they match the expected ranges, without the multiplier, so that a new
organization lands where Humaital would expect it ("figure what works").

Methodology 6.0.0 placed 13 of the 22 organizations in range. Reading its
results showed why it could do no better: 16 of the 22 had level 3 on nearly
every criterion. Ordinary corporate governance (a board committee, a code of
conduct, a privacy programme) earned the same level as a published
responsible AI programme, so the score was about 50 for almost everyone and
could not tell Microsoft from an airline. Three further defects were found by
reading the evidence itself:

1. **The early stage was held to the mature ladder.** Humaital's own site
   states commitments and assigns oversight. It scored 40.0.
2. **Third-person writing was not read.** The lexicon recognised "we" and a
   list of bodies as the accountable owner. Sites that write "Siemens has
   established", "Fidelity maintains" or "the University requires" earned
   commitments where the same sentence with "we" earned a control.
3. **Records of AI practice were missed and some false ones were credited.**
   "Delivered responsible AI training to nearly 20,000 engineers" and "In
   FY25" were not recognised. A bullet list that mentioned AI once and
   reported training hours three bullets later was credited as documented AI
   execution.

Humaital's published HAI Methodology v3.0 (humaital.com/rating-scoring,
effective November 2026, collected by the crawler during calibration) settles
two of these questions in its own words, quoted in the decision below.

## Decision

### Stage-Appropriate Expectations (D17)

The published text says the methodology "applies stage-appropriate
expectations", that an early-stage organization is evaluated on
"foundational purpose clarity, basic safety practices, and stated
accountability ownership", that "formal controls infrastructure is not
expected" and that "early design decisions are weighted heavily".

`scoring.stage_expectations.level_progress` credits the early band half a
level on every criterion that has admissible supporting evidence (rule
ADJ-STAGE-EXPECTATIONS). Growth and mature organizations earn nothing more.

### Evidence That Is Specifically About AI (D18)

The published evidence tiers describe "an organization's position on
responsible AI". General corporate governance still earns its level (D14).
`scoring.ai_specific` adds half of the next level when the rung that set the
level is carried by two separate passages about AI being governed, built or
used (rule ADJ-AI-SPECIFIC). It applies to stated commitments and specified
controls; from documented execution upwards the evidence must be about AI to
hold the rung at all.

A passage is AI-specific when a practice phrase stands within
`lexicons.ai_context.max_gap_chars` (200) of the words that earned its rung.
The same distance now applies to the AI context required for documented
execution, unless the section heading or the document title places the whole
passage in AI.

Two half levels make a level: an early-stage organization whose stated
commitments are about AI reaches the level a mature organization earns with a
specified control, which is what the published text describes.

The part of a level is stored (`criterion_decisions.level_progress`), each
link records whether it is AI-specific (`evidence_links.ai_specific`), and
both rules write their reasoning to the decision trace. The criterion ratio
is `(level - 1 + level_progress) / 4`.

### Whose Statement And What Kind Of Record (D19)

* The organization's own name counts as an accountable owner, in proposals
  and in classification.
* The same sentence repeated on several pages is one passage for
  corroboration.
* Findings about other organizations (`evidence_quality.research_terms`) and
  financial results (`financial_terms`) do not earn the execution rung.
* The date lexicon gained the plain year and fiscal-year forms; the result
  lexicon gained verbs of a governance activity having been carried out.
* When a long document's links are bounded, passages about AI are kept first.
* The archive fallback no longer spends its page budget on pages the Internet
  Archive never captured.
* A country and language prefix (`/us/en/`, `/global/en/`) names an edition
  of a site, not a section. The per-section page cap used to treat a whole
  country-structured site as one section and stop after six pages; PwC's
  archived site went from 26 pages with one about AI to 34 with its
  responsible AI pages.

## What Was Not Done

* No multiplier, no curve fitted to the ranges, no industry prior and no
  per-organization setting. Nothing reads the expected ranges except the
  calibration harness.
* A limit on how many criteria one AI passage may count toward was tested and
  rejected: it moved Home Depot into range and Microsoft and Goldman Sachs
  out.
* Requiring three or four AI-specific passages was tested and rejected for
  the same reason.
* The crawler still honours robots.txt and identifies itself honestly.

## Result

All numbers come from `tests/calibration/harness.py`: the real job chain
against a throwaway database, heuristic provider, evidence collected on 22
and 23 November 2026 and replayed from the HTTP cache on the final manifest.
"Sheet" is the score the owner recorded under methodology 5.0.0.

| Organization | Sheet | Expected | 6.0.0 | 7.0.0 | Against Range | Documents | Website | Criteria Above Level 3 |
|---|---:|---|---:|---:|---|---:|---|---:|
| Humaital | 63.5 | 65 to 75 | 40.0 | 68.4 | in range | 20 | succeeded | 18 |
| Accenture | 12.5 | 55 to 70 | 54.0 | 61.5 | in range | 36 | succeeded | 16 |
| PWC | N/A | 55 to 70 | 47.7 | 57.7 | in range | 34 | blocked | 13 |
| Pfizer | 51.5 | 50 to 70 | 50.0 | 50.0 | in range | 35 | succeeded | 0 |
| Roche | 30 | 50 to 70 | 50.0 | 55.7 | in range | 41 | succeeded | 9 |
| Costco | 38.5 | 35 to 55 | 47.7 | 47.7 | in range | 23 | succeeded | 0 |
| Walmart | 51.5 | 40 to 60 | 51.3 | 59.0 | in range | 30 | succeeded | 12 |
| Home Depot | 12.5 | 35 to 55 | 52.9 | 60.8 | +5.8 | 21 | succeeded | 16 |
| Microsoft | 100 | 65 to 80 | 55.1 | 67.1 | in range | 44 | succeeded | 20 |
| Meta | 19.5 | 50 to 70 | 50.0 | 61.8 | in range | 47 | succeeded | 19 |
| Fidelity | 25.5 | 50 to 70 | 42.6 | 47.7 | -2.3 | 34 | succeeded | 0 |
| Goldman Sachs | N/A | 55 to 75 | 50.0 | 56.8 | in range | 42 | blocked | 11 |
| MIT | 5.5 | 45 to 65 | 46.0 | 50.4 | in range | 40 | succeeded | 4 |
| Harvard | 0 | 40 to 60 | 39.1 | 47.1 | in range | 29 | succeeded | 2 |
| Foxconn | 0 | 25 to 45 | 46.1 | 46.1 | +1.1 | 29 | succeeded | 0 |
| Siemens | 17.5 | 50 to 70 | 47.4 | 54.6 | in range | 34 | succeeded | 9 |
| AA | N/A | 35 to 55 | 50.0 | 51.2 | in range | 22 | succeeded | 2 |
| Delta | N/A | 35 to 55 | 50.0 | 54.7 | in range | 38 | succeeded | 8 |
| Hilton | N/A | 35 to 55 | 50.0 | 50.0 | in range | 29 | succeeded | 0 |
| Marriott | N/A | 40 to 60 | 50.0 | 54.4 | in range | 21 | blocked | 7 |
| Chevron | 100 | 45 to 60 | 50.0 | 50.7 | in range | 15 | blocked | 1 |
| Shell | N/A | 40 to 60 | 50.0 | 50.0 | in range | 2 | succeeded | 0 |

19 of 22 are inside their range and 2 more are within 3 points. Under 6.0.0,
13 were inside; on the owner's sheet, 2.

The three outside:

* **Home Depot (+5.8).** Its values report and filings describe a Responsible
  AI Working Group, a governance committee for AI and board oversight of
  generative AI. The evidence reads like Goldman Sachs' and scores like it.
* **Fidelity (-2.3).** A private company; the site is a brokerage storefront
  and no AI governance statement was found.
* **Foxconn (+1.1).** Corporate governance and CSR pages earn level 3 on 17
  criteria; nothing about AI was found.

### Organizations Outside The Sheet

Their ranges are not ground truth: each is the span of the sheet's ranges for
the same industry (`tests/calibration/peer_check.yaml`). The first eight were
first run under 6.0.0 and were scored repeatedly while 7.0.0 was written,
though no rule or term was chosen from their text.

| Organization | Industry | Peer Range | 6.0.0 | 7.0.0 | Against Peer Range | Documents | Website |
|---|---|---|---:|---:|---|---:|---|
| IBM | Technology | 50 to 80 | 52.7 | 59.9 | in range | 44 | succeeded |
| JPMorgan Chase | Financial Services | 50 to 75 | 50.0 | 51.3 | in range | 45 | succeeded |
| Target | Retail | 35 to 60 | 48.6 | 48.6 | in range | 34 | succeeded |
| United Airlines | Travel | 35 to 55 | 50.0 | 52.0 | in range | 38 | blocked |
| Stanford University | Education | 40 to 65 | 46.0 | 52.4 | in range | 43 | succeeded |
| BP | Energy | 40 to 60 | 32.5 | 36.8 | -3.2 | 8 | blocked |
| Johnson & Johnson | Healthcare | 50 to 70 | 50.0 | 50.6 | in range | 40 | succeeded |
| Deloitte | Professional Services | 55 to 70 | 44.9 | 51.8 | -3.2 | 33 | succeeded |

The next nine were chosen and run for the first time after 7.0.0 was
finished. One term was added to the financial guard after reading their
credited passages (it moved Salesforce from 67.0 to 66.0 and nothing else).

| Organization | Industry | Peer Range | 7.0.0 | Against Peer Range | Documents | Website |
|---|---|---|---:|---|---:|---|
| Salesforce | Technology | 50 to 80 | 66.0 | in range | 43 | succeeded |
| Bank of America | Financial Services | 50 to 75 | 55.0 | in range | 36 | succeeded |
| Novartis | Healthcare | 50 to 70 | 64.0 | in range | 41 | succeeded |
| Lowe's | Retail | 35 to 60 | 47.5 | in range | 31 | blocked |
| Southwest Airlines | Travel | 35 to 55 | 51.9 | in range | 38 | succeeded |
| Hyatt | Hospitality | 35 to 60 | 48.9 | in range | 9 | succeeded |
| ExxonMobil | Energy | 40 to 60 | 50.0 | in range | 42 | succeeded |
| Yale University | Education | 40 to 65 | 43.1 | in range | 22 | succeeded |
| KPMG | Professional Services | 55 to 70 | 50.0 | -5.0 | 36 | succeeded |

14 of 17 are inside their peers' range. The three outside are a blocked site
with eight archived pages (BP) and two professional-services firms whose
sites describe client offerings more than their own governance (Deloitte,
KPMG).

## Limits

* Agreement is closest where the public record is readable. Organizations
  whose sites refuse the crawler are scored from archived copies and filings
  and tend to land low.
* A retailer that publishes an AI governance structure (Home Depot) scores
  like a bank that does (Goldman Sachs). The expected ranges separate them by
  sector; the evidence does not, and no sector prior was added.
* An organization with ordinary governance and no public AI governance lands
  near 50. That is inside most expected ranges but at the lower edge of the
  ranges that start at 50.
* The reading is still lexical. The half levels and the two-passage rule are
  drafts chosen against this set; D17, D18 and D19 are open for Humaital.
* All 22 organizations were used to choose these rules. The check on
  organizations outside the sheet is by analogy with peers, not ground truth.

## Versioning

Ontology 1.4.0 (two additive fields, migration `0011`), methodology 7.0.0
(scoring changed), ruleset 6.0.0 (two rules added).

## Validation

Run on the final manifest (hash `d3c49f26ba53`):

* `make ontology-validate`, `make codegen-check`, `make check-bump
  BASE=git:HEAD` (ontology minor, methodology major).
* Lint, format and `mypy --strict` on every package, service and test tree.
* Unit tests, the Postgres suites with roles not enforced and enforced, and
  the console typecheck, lint, tests and build: see the commit message for
  the counts.
* The calibration run above, twice: online on 23 November (collecting pages
  the crawl changes reach) and offline from the cache on the final manifest.
  The two agree on every organization except Salesforce, as noted.
