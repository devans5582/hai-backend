# Assessment Validation November 16 2026

## Scope And Conclusion

This review covers all nine assessment PDFs and the preliminary developer
findings document in the [shared report folder](https://drive.google.com/drive/u/0/folders/1elrCaxB8ko1g0JhPPrjKyGJcvgD1K5KR).
The PDFs contain 216 pages, 36 collected documents and 814 frozen evidence
links. All were assessed on November 10 2026. Four results are N/A; the five
numeric results range from 0 to 12.5. These are recorded engine outputs, not
independent ratings of the organizations.

The batch establishes acquisition, attribution and evidence-classification
problems. It does not establish replacement scores or justify a blanket
increase. Every numeric report says `Caps applied none`: neither the old
85-point overall ceiling nor the 75-point low-confidence ceiling caused
these low results. Criterion-level caps are a separate matter.

## Reported Baseline

Every report pins ontology `1.2.0`, methodology `2.0.0`, ruleset `1.1.0`,
prompt `1.0.0` and model `heuristic:ladder-1`. These runs used the heuristic
provider. Website references to Methodology v3.0 do not change those pins.
Confidence below is the precise value printed in the certification gate;
the cover rounds it to a whole percentage. N/A means no numeric score.

| Organization | Submitted Domain | Report Version | Score | Confidence | Counted | Documents | Links |
|---|---|---|---:|---:|---:|---:|---:|
| AA | aa.com | 3 of 3 | N/A | N/A | 0/20 | 0 | 0 |
| Accenture | accenture.com | 1 of 1 | N/A | N/A | 0/20 | 3 | 77 |
| Chevron | chevron.com | 1 of 1 | 12.5 | 12.5% | 14/20 | 3 | 283 |
| Delta | delta.com | 2 of 2 | N/A | N/A | 0/20 | 0 | 0 |
| Humaital | humaital.com | 3 of 3 | 7.7 | 9.7% | 20/20 | 4 | 72 |
| Microsoft | microsoft.com | 2 of 2 | 5.3 | 6.2% | 20/20 | 15 | 356 |
| Phizer | phizer.com | 2 of 2 | N/A | N/A | 0/20 | 0 | 0 |
| Roche | roche.com | 1 of 1 | 7.4 | 8.4% | 20/20 | 11 | 26 |
| Shell | shell.com | 1 of 1 | 0 | 0% | 20/20 | 0 | 0 |

Humaital was submitted as early stage/small; the other eight as
mature/enterprise. Every report shows Google News RSS blocked and Semantic
Scholar rate-limited. There are 443 admissible links: 66 supporting, 87
contradicting and 290 neutral. Another 371 links are stale. An admissible
link is not necessarily supporting evidence or evidence of execution.

## Disposition Of The Eight Developer Requests

### 1 Zero Document Handling

**Confirmed defect.** Shell reports website success, no documents and no
links, but counts 20 missing criteria and assigns zero. Delta and AA also
collect nothing, but source failures correctly produce unavailable criteria.
Distinguish a usable search with no relevant evidence from an HTTP success
that yielded no readable content. The latter must not establish poor governance.
Paths: `hai_pipeline/connectors/website.py`, `hai_pipeline/acquire.py`,
`hai_engine/rules/builtin.py:gate_coverage`. A JavaScript-shell regression
checks that empty successful responses become an acquisition limitation.

### 2 Retrieval And Admissibility

**Confirmed retrieval and classification defects; some exclusions intentional.**
All 77 Accenture links are stale; its SEC sources are dated 2018, 2022 and
2023. Microsoft has 226 stale links from 2022 and October 24 2024 filings.
The latter is just outside the 24-month window at assessment time. Preserve
freshness checks, but request current filings before spending the source budget.
Paths: `hai_pipeline/connectors/edgar.py`, `hai_pipeline/admissibility.py`.

Separately, admissible mission statements and assigned review procedures
were neutral. This is not an admissibility failure: the proposer and
classifier fail to recognize substantive positive statements. Paths:
`hai_pipeline/proposals.py`, `hai_core/signals.py`,
`hai_engine/classification.py`, criterion retrieval hints in `ontology/`.

### 3 AI Relevance Of Negative Signals

**Confirmed scope and attribution defects.** Microsoft's 20 admissible
negative links come from two recycling-page passages, each linked to ten
criteria. One is a legal-navigation list; another warns that authorities
"may take enforcement action for improper disposal of WEEE."
Neither establishes an AI incident or wrongdoing by the assessed company.

Chevron's 67 admissible negative links concern environmental notices,
refinery equipment, well control and water regulations. Their presence in
an SEC filing does not establish an AI connection. Company-authored SEC
disclosures were also labeled regulator records, risking unwarranted
verification credit and incident substantiation. Paths:
`hai_pipeline/proposals.py:assessment_negative`, `hai_pipeline/incidents.py`,
`hai_pipeline/connectors/edgar.py`, `hai_pipeline/publishers.py`.

### 4 Missing Unavailable And Excluded Criteria

**Intentional scoring rule, with the acquisition defect in request 1.**
Missing criteria enter at level 1, whose ratio is zero. Unavailable and
explicitly not-applicable criteria are excluded. Humaital and Roche each
count 16 missing criteria alongside four observed criteria. That denominator
explains part of their low aggregate scores; excluding every missing
criterion would be a new methodology decision, not a retrieval correction.
Paths: `ontology/vocabularies/coverage_state.yaml`,
`hai_engine/rules/builtin.py:gate_coverage`, `hai_engine/scoring.py:aggregate`.

### 5 Partial Pillar Normalization

**Intentional arithmetic with a reporting and comparability limitation.**
Chevron excludes all four Impact criteria and two Purpose criteria.
Its live pillars represent 80% of the nominal weight. The engine renormalizes
that weight, producing 12.5 rather than approximately 10 on an unchanged
100-point denominator. Show coverage alongside the score; a partial result
must not be presented as directly comparable to complete evidence coverage.
Paths: `hai_engine/scoring.py:aggregate`, `hai_engine/reporting.py`,
`hai_engine/report_pdf.py`, `hai_engine/rules/builtin.py:gate_outcome_status`.

### 6 Entity Resolution And Inputs

**Input and verification limitations.** The actual input is `Phizer` at
`phizer.com`, not a verified assessment of Pfizer. `AA` is abbreviated;
`aa.com` alone does not prove the intended identity. Delta's website failed
with `connecterror`. Keep submitted names/domains and verified identifiers
distinct; do not silently redirect an assessment to a guessed company.
Paths: `hai_api/schemas.py`, `hai_core/assessments.py`,
`hai_pipeline/entity_resolution.py`, `hai_pipeline/urls.py`.

### 7 Connector Success And Evidence Success

**Confirmed acquisition defects and external access limitations.** An empty
optional connector can legitimately succeed when no URLs or credentials were
supplied. That does not mean evidence was collected. News blocking and
Scholar throttling are persistent limitations in all nine reports, not
governance findings. Microsoft's 15 documents also include three entries for
the same Trust Center URL. Humaital collects only four pages; Roche's eleven
are largely general governance/sustainability pages. Prioritize relevant AI
policies and report links, follow governance hubs, deduplicate redirects and
respect bounded retries. Paths: `hai_pipeline/http.py`,
`hai_pipeline/connectors/website.py`, `hai_pipeline/acquire.py`, connector runs.

### 8 Confidence And Certification Trace

**Reported outputs confirmed; exact calculation needs structured evidence.**
The PDFs show aggregate confidence, gates and quoted classifications, but
omit exact criterion component values and clip appendix quotations. A PDF
alone cannot replay the frozen snapshot or establish a new score. Use the
snapshot, findings and criterion trace for a worked calculation. Preserve
source-cluster deduplication, freshness, omissions, contradictions and human
certification gates. Paths: `hai_engine/rules/builtin.py:_conf_components`,
`hai_engine/rules/builtin.py:gate_certification`, `hai_engine/decision.py`,
`hai_engine/certification.py`, assessment trace/report endpoints.

## Representative Regression Cases

| Source Case | Before In Report | Corrected Behavior Or Limit |
|---|---|---|
| Humaital mission, PDF page 19: "Our mission is to provide an independent, evidence-based standard" | Mission Clarity neutral, level 1 | Recognize a substantive mission statement; this alone proves no operational execution. |
| Humaital assigned oversight, page 19: "Designated human oversight is responsible for reviewing material findings" | Neutral | Recognize assigned review duties without demanding a numerical threshold. |
| Chevron AI oversight, page 36: "The Board additionally oversees risks and opportunities associated with technology, including artificial intelligence" | Neutral | Recognize relevant assigned AI oversight; do not promote generic financial governance. |
| Microsoft recycling/legal passages, pages 22-24 | 20 negative links across many criteria | Produce no AI incident from navigation or a hypothetical disposal warning. |
| Shell empty website response | Zero score from 20 missing criteria | Record no usable collection as an evidence-access limitation. |
| Roche treasury risk policy, pages 9 and 19 | Documented execution of AI Risk Mitigation | Require an AI connection; financial treasury policy does not prove AI control execution. |

Humaital's newsroom founding story also receives execution credit, and
Chevron's financial-audit committee duties receive independent-verification
credit. Correct false positive evidence as well as missed positive evidence.
A policy describing what HAI evaluates in other organizations must not be
mistaken for proof that Humaital itself operates that control.

## Change And Reassessment Limits

The preliminary DOCX requests causes, classification of findings and
reproducible tests. It supplies no replacement score curve. Published v3
alignment is documented in a separate methodology decision record; do not
infer numerical multipliers from obsolete cached website text.

Keep these historical PDFs and stored results unchanged. Version ontology,
methodology and rules changes, then run new assessments with recorded inputs,
collection outcomes, model/provider and old/new version pins. Improved
retrieval and classification can raise or lower individual results. The
folder contains neither Delta's earlier 65.8 report nor the error screenshot,
so it cannot establish the exact historical difference or HTTP failure.

## Source Provenance

Original bytes were retained in `/tmp/hai-assessments-20261116`; PDFs and
DOCX are not committed. SHA-256 values below identify the reviewed files.

| Filename | SHA-256 |
|---|---|
| HAI-Score-AA-v3.pdf | `83f5921b9d21557fdbe8daf665820ac71902b2c230f25ad8846c6c8b3e17a180` |
| HAI-Score-Accenture-v1.pdf | `316569e3a4086ad4db9735d434fb8c3a4c2437ffc335dc3db8dbb74f5d289c71` |
| HAI-Score-Chevron-v1.pdf | `a14a90b8dbf772248f7eb8bfbbbef8f10b089e25aec5fa2b5998c326bfd03ad5` |
| HAI-Score-Delta-v2.pdf | `6660fb5bcdf755b44e929acad49d295ce5254bdf69add20ed444ad8b855297de` |
| HAI-Score-Humaital-v3.pdf | `abd8429db9509b2c56977dbd9e8e136b77ab35076b4f920fada0a40bc1671a23` |
| HAI-Score-Microsoft-v2.pdf | `70c67a528c60d1f2fc52ee4054c8af9431d7e43d6d7d94e7425351903e285bba` |
| HAI-Score-Phizer-v2.pdf | `ddf7b3f5e558c0edf0edad5b3860345d79a4259ef603b1ad98b6529e29eee96d` |
| HAI-Score-Roche-v1.pdf | `6ea3b7dae8ac01523302faa77e8b4a2c431647a6f13fc6eb843bf60acb3d6e9e` |
| HAI-Score-Shell-v1.pdf | `17a36c7f4855bcb44bdf240fd89167c4b6a9e2988d5436824acfe9f3f00d5a7b` |
| Humaital_HAI_Initial_Developer_Findings.docx | `d83c8b6f6416415311a441a40ed1c463f885b8d3ce3704712f83389b5ba37153` |
