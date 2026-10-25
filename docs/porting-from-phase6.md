# Porting From Phase 6

The Phase 6 Node/Express service on `main` is kept unchanged under
`legacy/express-api/` as read-only reference. This document records what the
new Python platform carries over from it, what it corrects, and what it drops
on purpose. Every claim below points at a file and line in the legacy code.
Paths are relative to `legacy/express-api/`; line numbers are those of the
files as they stand on `main` (the move does not change content).

Terminology used below: "FIX-n" is the Phase 6 fix number written in the
legacy file headers. "IC-nn" and "AT-nn" are the integrity constraints and
acceptance tests from `HAI_Ontology_v1_Specification (1).docx` at the repository root.

## 1. Carried Over

Everything in this section is Humaital methodology content or a behaviour
that is correct and worth keeping. Constants are imported exactly; where the
new code changes the shape (for example a map becomes a YAML vocabulary) the
values are unchanged.

### 1.1 Scoring Constants

| Item | Legacy location | Value | Where it lives now |
|---|---|---|---|
| Pillar max points | `src/services/report-generator.js:1242` | Trust 20, Accountability 15, Purpose 15, Safety 15, Transparency 15, Impact 20 | `ontology/methodology/pillars.yaml` as weights 0.20, 0.15, 0.15, 0.15, 0.15, 0.20 (sum 1.0) |
| Criterion ratio | `src/services/report-generator.js:1250` | `(level - 1) / 4` | `methodology.yaml` scoring, `hai_engine.scoring` |
| Pillar mean | `src/services/report-generator.js:1252` | mean of criterion ratios times pillar max | `hai_engine.scoring` (materiality weighting is decision D2) |
| Materiality-weighted pillar mean | `src/services/evidence-weighting.js:209-225` (instructions for bundle.js) | ratio times materiality, divided by total materiality | `methodology.yaml` scoring `pillar_aggregation` |
| Criterion materiality weights | `src/services/evidence-weighting.js:51-96` | 20 values from 0.8 to 1.4, with pillar sums 4.4 / 3.8 / 3.1 / 4.0 / 3.5 / 4.3 | `materiality_weight` in each `criteria/<CODE>.yaml`, vocabulary `materiality` |
| Score cap | `src/services/report-generator.js:1019` | 85 | `methodology.yaml` scoring `score_cap`, rule CAP-SCORE-CEILING |
| Low-confidence score cap | `src/services/report-generator.js:1023-1024`, applied at `1222-1224` | confidence below 70 caps the score at 75 | rule CAP-SCORE-LOW-CONFIDENCE |
| Partial-evaluation confidence ceiling | referenced at `src/services/scraper.js:765` ("69% confPercent ceiling in bundle.js") | 69 | `methodology.yaml` confidence `partial_ceiling` (draft; value is only referenced, not defined, in the legacy backend) |
| Negative-signal confidence ceiling | `src/services/negative-signal-overrides.js:44, 299` | 20 | rule CONF-INCIDENT-CEILING for severity low |
| Certification threshold | `src/services/report-generator.js:199` ("minimum verified score of 70") | 70 | `methodology.yaml` certification `threshold`, rule GATE-CERTIFICATION (decision D3) |
| Report delivery gate | `src/routes/send-report.js:124-138` | score above 0 and confidence above 10 | folded into outcome status `insufficient_evidence` and `confidence_too_low` |
| Level labels | `src/services/report-generator.js:1262` | Not Present, Initial, Developing, Established, Advanced | label dictionary (generated) |
| Pillar status labels | `src/services/report-generator.js:117` | Strong, Progressing, Developing, Needs Attention | report label dictionary |

### 1.2 Evidence Weighting And Confidence (FIX-8)

| Item | Legacy location | Value |
|---|---|---|
| Source tier weights | `src/services/supplementary-evidence.js:97-108` | high 1.0 (EDGAR, ISO_42001, NIST_RMF, GOVINFO), medium 0.6 (OECD, ACADEMIC, NEWS, NEWS_NEGATIVE), low 0.25 (GITHUB, WAYBACK) |
| Role multipliers | `src/services/evidence-weighting.js:116-120` | justifies 1.0, supports 0.5, contradicts 0.0 |
| Evidence type multipliers | `src/services/evidence-weighting.js:122-126` | governance 0.7, operational 1.0, external 1.3 |
| Base contribution | `src/services/evidence-weighting.js:141` | 30 |
| Contribution formula | `src/services/evidence-weighting.js:143-152` | tier x role x type x materiality x 30 |
| Corroboration bonus | `src/services/evidence-weighting.js:171-178` and `supplementary-evidence.js:677-684` | 8 for two sources, 15 for three or more, scaled by materiality |
| Confidence clamp | `src/services/evidence-weighting.js:184` | 0 to 100 |

These become the parameters of rule CONF-EVIDENCE. Tier weights move onto the
`source_tier` vocabulary as attributes (decision D9). The spec maps publisher
types to tiers T1 to T4; the Phase 6 high/medium/low weights are attached to
those tiers as T1 1.0, T2 0.6, T3 0.6, T4 0.25 unless Humaital supplies
different values (marked draft).

### 1.3 Time Decay (FIX-10)

| Item | Legacy location | Value |
|---|---|---|
| Decay curves (half-life months, floor) | `src/services/time-decay.js:34-60` | ISO_42001 24/0.6, NIST_RMF 24/0.55, EDGAR 18/0.4, GOVINFO 24/0.4, OECD 30/0.5, ACADEMIC 36/0.5, WEBSITE 12/0.3, WAYBACK 18/0.25, GITHUB 18/0.2, NEWS 3/0.1, NEWS_NEGATIVE 6/0.4, DEFAULT 18/0.3 |
| Exponential decay | `src/services/time-decay.js:154-159` | `max(floor, exp(-ln2 / halfLife * months))` |
| Undated evidence age | `src/services/time-decay.js:64` | 18 months, disclosed as "date not detected" |
| Active certificate | `src/services/time-decay.js:122-141` | full weight until expiry, then decays from the expiry date |
| Year-only dates | `src/services/time-decay.js:84-87` | 1 January of that year |
| Freshness labels | `src/services/time-decay.js:232-240` | Current 80+, Mostly current 60+, Mixed age 40+, Largely stale |

Carried as `methodology.yaml` freshness. The curve key changes from legacy
source code to publisher type (decision D9) with the legacy codes kept as
aliases. See section 2.3 for why decay is now actually applied.

### 1.4 Negative Signal Overrides (FIX-9) As Incident Severity

| Legacy severity | Legacy location | Effect | New incident severity |
|---|---|---|---|
| force_level_1 | `src/services/negative-signal-overrides.js:41, 65-78` | level set to 1 | critical |
| reduce_2_steps | `:42, 83-110` | level minus 2, floor 1 | high |
| reduce_1_step | `:43, 112-125` | level minus 1, floor 1 | moderate |
| confidence_floor | `:44, 129-140, 295-312` | level unchanged, confidence capped at 20 | low |

Also carried: the source-by-text severity map (`:60-141`), the default
classification for unmatched negative signals (`:171-186`), the affected
pillars per tier (`:72, 90, 105, 120, 135`), the non-accusatory wording rules
(`:7-22, 52-58`) and the user-facing descriptions (`:75-77, 92-94, 107-109,
122-124, 137-139`). These become the `lexicons.negative_signals` block in
`methodology.yaml` and the `incident_severity` vocabulary. Severity rank order
(`:319-324`) is kept as the vocabulary rank.

### 1.5 Proof Of Execution (FIX-12)

| Item | Legacy location |
|---|---|
| Execution keyword patterns by category (metrics, process, control, audit, impact) | `src/services/proof-of-execution.js:42-96` |
| Category weights | `:100-106` (metrics 1.0, process 0.8, control 0.7, audit 1.0, impact 0.9) |
| Level thresholds | `:132-149` (audit or metrics with weight 1.8 or more gives verified; metrics, or process plus control, gives partial; anything else asserted; nothing gives none) |
| Execution bonus | `:279-287` (verified +20, partial +10, asserted 0, none -5) |
| Execution gap wording | `:339-344` |
| Prompt wording for the four execution levels | `:242-268` |

Carried as the `execution_level` vocabulary and the `lexicons.execution`
block. See section 2.2 for the change from whole-site to per-span scoring.

### 1.6 Criterion Register Inputs

| Item | Legacy location |
|---|---|
| The 20 criterion IDs, labels and pillars | `src/services/openai.js:13-40`, `src/services/supplementary-evidence.js:27-80`, `src/services/report-generator.js:956-963` |
| Rubric indicator IDs (R, S, G and O items per criterion) | `src/services/openai.js:52-134` |
| Criterion keyword map (retrieval hints) | `src/services/supplementary-evidence.js:111-132` |
| Source to pillar relevance map | `src/services/supplementary-evidence.js:83-94` |
| Generic level meanings 1 to 5 | `src/services/openai.js:149-154` |

The legacy IDs (for example `safety_risk_mitigation`) become the `legacy_id`
alias of the new codes (for example `SAF-01`, decision D7). Indicator IDs are
carried as `indicators` with `label: null` because the legacy backend holds
only the IDs; the labels live in the WordPress bundle that is not in this
repository. Level descriptors per criterion are not in the legacy code at all,
so every criterion file is `content_status: draft` with a `TODO(humaital)`.

### 1.7 Inputs, Sources And Infrastructure

| Item | Legacy location | Kept as |
|---|---|---|
| Stage input values | `src/routes/evaluate.js:76` default `startup`; `src/services/report-generator.js:899-901` startup / growth / enterprise | aliases on the `stage_band` vocabulary |
| Size input values | `src/routes/evaluate.js:77` default `1-10`; `src/services/report-generator.js:905-913` 1-10, 11-50, 51-200, 200+, 1000+ | aliases on the `size_band` vocabulary |
| Governance maturity mapping | `src/services/report-generator.js:892-921` (emerging, scaling, institutional; conservative merge) | `methodology.yaml` certification stage/size table (decision D3) |
| Allowed CORS origins | `server.js:14-24` plus suffix rules at `:32-39` | `HAI_CORS_ORIGINS` default list |
| Governance page paths | `src/services/scraper.js:44-84` | WEBSITE connector `seed_paths` in `config/connectors.yaml` |
| Governance link keywords | `src/services/scraper.js:15-42` | WEBSITE connector `link_keywords` |
| Block detection | `src/services/scraper.js:179-185` keywords and status codes 403, 406, 429, 503 | connector run outcome `blocked` |
| Hard-skip and low-value paths | `src/services/scraper.js:134-147` | WEBSITE connector `skip_paths` |
| Budgets | `src/services/scraper.js:418-419` 50 s and 10 confirmed pages; `:186` 5 discovered links | connector `limits` |
| Direct URL input | `src/routes/evaluate.js:82-85` | DIRECT_URL connector |
| Entity resolution signal weights | `src/services/entity-resolver.js:226-240` (name 0.35, domain 0.40, EDGAR 0.25) | `hai_pipeline.entity_resolution` confidence |
| Domain match rules | `src/services/entity-resolver.js:176-195` | same, but see section 2.5 |
| EDGAR filer-name entity match | `src/services/supplementary-evidence.js:156-167` | EDGAR connector |
| EDGAR filing dedupe key | `src/services/supplementary-evidence.js:181-188` | EDGAR connector |
| Negative news patterns | `src/services/supplementary-evidence.js:551-556` | `lexicons.negative_signals` |
| Wayback pre-2015 cutoff | `src/services/supplementary-evidence.js:450-456` | WAYBACK connector `min_year` |
| Academic entity relevance rule | `src/services/supplementary-evidence.js:320-361` | ACADEMIC connector (whole-word, see 2.1) |
| Benchmark definition | `src/services/db.js:69-107` most recent record per domain, averaged by industry | `GET /v1/benchmarks/industries` |
| Benchmark eligibility | `src/services/db.js:53-55`, `report-generator.js:1513` access-limited runs excluded | outcome `access_limited` excluded from peers |
| Response envelope idea | `server.js:134, 140` `{ success, data }` | replaced by `{ error: { code, message, details } }` on errors |
| Health probe | `src/routes/health.js:10-16` | `/health` |
| 7-day re-assessment window | `src/routes/evaluate.js:98-154` | `Idempotency-Key` on create plus an explicit `/reassess` |

### 1.8 Evaluation States That Become Outcome Statuses

| Legacy state | Legacy location | New outcome status |
|---|---|---|
| access_limited | `src/services/report-generator.js:1431-1433, 1508-1510` | access_limited (requires failed or blocked connector runs, IC-15) |
| insufficient_evidence | `src/services/report-generator.js:867-870, 937-949` | insufficient_evidence |
| raw score 0 with signals | `src/services/report-generator.js:1433` | governance_baseline |
| partial_evaluation | `src/services/report-generator.js:871-876` | not a status; becomes lower confidence plus coverage states per criterion |

## 2. Corrected

Each defect below was confirmed in the legacy code at the cited lines. Each
has, or will have, a named regression test in the new code; the test column
names the test function that must exist before the phase is marked done.

### 2.1 Substring Term Matching

Keyword checks use `String.includes` on lowercased text, so a term matches
inside a longer word.

* `src/services/supplementary-evidence.js:600` maps text to criteria with
  `_lower.includes(kw)`. Keyword `board` (`scraper.js:30`) matches
  "dashboard" and "onboarding"; `press` (`scraper.js:31`) matches
  "impressive"; `kpi` (`supplementary-evidence.js:130`) matches any word
  containing those letters.
* `src/services/negative-signal-overrides.js:157, 164` match severity
  patterns with `includes`.
* `src/services/supplementary-evidence.js:560` flags negative news with
  `includes`.
* `src/services/scraper.js:152` works around the problem for one term by
  padding it with spaces (`' ai '`), which also misses "AI," and "AI.".
* `src/services/report-generator.js:351` uses `/disclaimer/i` without word
  boundaries.

Correction: every lexicon term compiles to a whole-word regular expression
with an explicit `*` suffix for prefixes (for example `discriminat*`).
Regression test: `test_term_regex_is_whole_word`.

### 2.2 Proof Of Execution Taken As A Site-Wide Maximum

`src/services/proof-of-execution.js:160-172` computes an execution level for
the whole combined site text and then takes the higher of that and each
item's own level, so one "SOC 2" mention anywhere upgrades every evidence
item. `:189-193` then rewrites the item's role from `supports` to
`justifies`, which also violates the rule that polarity never changes.

Correction: execution level is computed per span from its own quote only,
stored on the link, and never changes polarity.
Regression tests: `test_execution_patterns`, `test_execution_is_per_span`,
`test_polarity_is_immutable` (database trigger, IC-01).

### 2.3 Time Decay Computed But Never Applied

`src/services/time-decay.js:193-210` contains the instruction to multiply the
contribution by the decay factor, but `src/services/evidence-weighting.js:143-152`
(the function it says to change) has no decay term, and
`src/services/supplementary-evidence.js:674` calls that unchanged function.
`annotateWithTimeDecay` at `:749` only adds display fields.

Correction: CONF-EVIDENCE multiplies each link's contribution by its freshness
decay. Freshness is computed against the snapshot time, not the wall clock, so
replay is deterministic. Undated evidence is decayed, never marked stale.
Regression tests: `test_freshness_decay_and_certificates`,
`test_undated_evidence_is_never_stale`, `test_decay_is_applied_in_confidence`.

### 2.4 News Items All Dated Today

`src/services/supplementary-evidence.js:571` sets `dateIssued` to the current
date for every headline; `:570` stores the RSS search URL instead of the
article URL; the RSS `pubDate` and `source` elements are never read
(`:546-549` extracts titles only). Every news item therefore decays as if
published today and has no publisher.

Correction: the NEWS connector reads `pubDate`, `link` and `source` per item,
creates one source document per article with its publisher, and clusters
syndicated copies (IC-09).
Regression tests: `test_news_items_carry_real_dates_and_publishers`,
`test_simhash_finds_syndicated_copies`.

### 2.5 Entity Resolution Defects

* `src/services/entity-resolver.js:89-92` reads the SEC CIK from Wikidata
  property P1566, which is the GeoNames ID. The CIK is P5531.
* `src/services/entity-resolver.js:140-143` takes the first EDGAR full-text
  hit for the company name as the CIK, with no filer-name check. The filter
  that exists in `supplementary-evidence.js:156-167` is not used here.
* `src/services/entity-resolver.js:187` treats "one domain contains the
  other" as a match, so `example.com` matches `notexample.com`.
* `src/services/entity-resolver.js:333` sets `isPublicCompany` from any CIK,
  verified or not, and `supplementary-evidence.js:513-532` guesses it from a
  Wikipedia snippet.

Correction: Wikidata P856, P5531, P1278, P452, P749; GLEIF for LEI; SEC
company tickers for CIK; identifiers stored on the organization only when the
official website's registrable domain equals the submitted domain.
Regression tests: `test_registrable_domain`,
`test_identifiers_verified_only_on_domain_match`,
`test_wikidata_properties_are_the_right_ones`.

### 2.6 GitHub Organization Guessed From A Name Slug

`src/services/supplementary-evidence.js:487-488` turns the company name into a
slug and searches `org:<slug>`. "Wells Fargo" becomes `org:wells-fargo`,
which may be an unrelated account.

Correction: GITHUB runs only with an organization handle found on the
official website or in Wikidata (P2037), otherwise it records an empty run.
Regression test: `test_github_requires_a_verified_handle`.

### 2.7 Wayback Snapshot Existence Treated As Support For Every Criterion

`src/services/supplementary-evidence.js:449-469` calls the availability API
and, when a snapshot exists, creates an item whose text is "Archived
governance page found", with `relevantPillars` set to all six pillars
(`:93`) and `role: supports`. The archived page is never fetched; the only
"evidence" is the URL path (`:465`).

Correction: WAYBACK fetches the archived page itself, extracts text, and the
result is a normal self-published source document with the snapshot date as
`published_at`. Metadata alone never lifts maturity above none (IC-06).
Regression tests: `test_metadata_is_not_evidence`,
`test_wayback_fetches_the_archived_page`.

### 2.8 Fixed-Length Truncation And One Slice For All Criteria

* `src/services/scraper.js:187, 195, 755-758` cap the site at 30,000
  characters and each page at 4,000.
* `src/routes/evaluate.js:241-244` cuts the combined text to 15,000.
* `src/services/openai.js:307` sends the first 14,000 characters in one
  prompt for all 20 criteria (`:305-321`).
* `src/services/report-generator.js:1368-1370` sends an 8,000 character
  preview for the narrative.

Correction: each page is its own content-addressed document; spans are
selected per criterion by retrieval hints into a size-limited evidence pack,
and omitted spans are counted into uncertainty (AT-09).
Regression tests: `test_spans_have_exact_offsets`,
`test_evidence_pack_is_per_criterion_and_counts_omissions`.

### 2.9 Crash On Direct URLs

`src/services/scraper.js:383, 391, 395` write to `combinedText`,
`successfulPages` and `seenPageFingerprints` inside the direct URL loop, but
those variables are declared with `let` and `const` at `:425-444`, after the
loop. Any request that supplies `directUrls` throws a temporal dead zone
`ReferenceError`, which `evaluate.js:209-212` swallows as "blocked".

Correction: DIRECT_URL is a connector with its own run record.
Regression test: `test_direct_urls_are_fetched_and_recorded`.

### 2.10 Blocked Sources Scored As Missing Evidence

* `src/services/scraper.js:821-844` returns stub text for every forced path
  when the homepage is unreachable.
* `src/services/openai.js:308` instructs the model to "assign level 1 to all
  criteria" when no text was retrieved, and `:294` says to assign level 1 when
  no evidence is found; the two cases are indistinguishable downstream.
* `src/services/report-generator.js:1431-1433` computes `access_limited` but
  still emits a score and narrative; `send-report.js:124-138` is the only
  place a bad run is stopped.

Correction: every connector run records its outcome (IC-16). A criterion whose
sources were blocked or failed is `unavailable` and excluded from the score,
not zeroed (IC-15). Outcome status `access_limited` is set by the rules engine.
Regression tests: `test_unavailable_only_when_a_connector_failed`,
`test_unavailable_criteria_are_excluded_not_zeroed`,
`test_blocked_sources_are_unavailable_not_missing` (end to end).

### 2.11 Scores Computed In The Browser And Patched Into Logs

* `src/routes/log-patch.js:47-50` accepts `final_score`, `confidence_score`
  and `certification_status` from the browser; `src/services/analysis-logger.js:152-213`
  writes them over the stored row.
* `src/services/report-generator.js:14-17, 46-47, 1444-1451` state that the
  authoritative calibration happens in `bundle.js`.
* `src/services/negative-signal-overrides.js:482-544` and
  `src/services/evidence-weighting.js:195-229` are instructions for the
  frontend to apply overrides and materiality.
* `src/routes/benchmark.js:44-45` stores a client-supplied score.

Correction: the rules engine is the only writer of criterion decisions,
results and outcome status (IC-12); results are append-only; the browser
renders what is stored (AT-10). There is no log patch route and the benchmark
endpoint reads stored results.
Regression tests: `test_append_only_tables_refuse_updates`,
`test_result_tables_are_writable_only_by_engine_role`,
`test_public_endpoints_and_auth`.

### 2.12 The Model's Output Sets The Score Directly

* `src/services/openai.js:384-395` clamps the model's levels and uses them as
  the criterion levels; `src/services/report-generator.js:1240-1255` sums
  them into the raw score.
* `src/services/openai.js:389` checks only that `items` is an array; it never
  checks that cited items correspond to any text.
* `src/services/openai.js:181-261` instructs the model to assign "AT LEAST
  level 2" or "level 3" when certain phrases appear, and `report-generator.js:1356`
  forces pillar labels of "Developing or better". These steer scores upward
  independent of evidence.

Correction: findings are advisory (principle 6). The validator rejects
findings whose citations are not in the snapshot or the criterion's pack
(IC-04), whose quotes do not match stored text (IC-03), or that claim credit
above stated commitment without quoted text (IC-06). The rules engine caps
the level by the evidence ladder (CAP-MATURITY).
Regression tests: `test_bad_findings_are_rejected`,
`test_level_is_capped_by_the_evidence_ladder`, `test_a_good_finding_passes`.

### 2.13 Further Corrections Found During The Read

| Defect | Legacy location | Correction | Test |
|---|---|---|---|
| Supplementary sources fetched only when the website scrape was partial (handover P0) | `src/routes/evaluate.js:219-223` | every enabled connector runs on every assessment | `test_every_connector_runs_and_is_recorded` |
| Negative signal applied to every criterion in up to three pillars, once per signal, against a proxy state | `src/services/negative-signal-overrides.js:214-218`, `supplementary-evidence.js:796-803` | one incident per real event, one adjustment per incident per assessment on its most material criterion (IC-10) | `test_incident_adjusts_only_its_target_criterion`, `test_event_keys_bucket_by_month` |
| Alleged news treated the same as a substantiated record | `src/services/supplementary-evidence.js:561-563, 575` | incidents start `alleged` unless the publisher is a regulator; alleged incidents go to review with no automatic effect (IC-11) | `test_alleged_incident_has_no_automatic_effect`, `test_incidents_start_conservative` |
| Maturity gate set by source tier and item count | `src/services/supplementary-evidence.js:641-664` | maturity rung from quote content; tier never sets maturity | `test_independence_comes_from_the_publisher_not_the_tier`, `test_owner_and_threshold_is_a_specified_control` |
| Confidence uses the first item's execution level only | `src/services/supplementary-evidence.js:687` | execution bonus is per link and order independent | `test_a_source_cluster_counts_once`, `test_independent_corroboration_raises_confidence` |
| Evidence silently capped at 20 items | `src/services/supplementary-evidence.js:737-746` | omissions are counted and lower confidence (AT-09) | `test_evidence_pack_is_per_criterion_and_counts_omissions` |
| Service functions resolved by "any exported function" (handover P1) | `src/routes/evaluate.js:20-38` | typed imports, mypy strict | import-time check |
| Unknown origins receive `Access-Control-Allow-Origin: *` | `server.js:48-51` | unknown origins get no CORS headers | `test_cors_denies_unknown_origins` |
| Shared secret accepted from the request body and compared with `===` | `server.js:82-83` | API keys as HMAC with a server pepper, header only, constant-time compare; JWTs for reviewers | `test_public_endpoints_and_auth`, `test_api_keys_are_hashed` |
| Crawled text and instructions mixed in one prompt, no injection screening (IC-17) | `src/services/openai.js:305-321`, `report-generator.js:1368-1396` | static system prompt; evidence as JSON data; injection lexicon makes a span `inadmissible_untrusted` | `test_injection_is_detected`, `test_injection_never_reaches_the_model` |
| Semantic Scholar query never requests affiliations, so affiliation matching at `:338-341` always sees an empty list; domain tokens of 3 letters match inside words | `src/services/supplementary-evidence.js:368, 357-358` | ACADEMIC requires a whole-word organization name or verified domain match in title, abstract or requested affiliation fields | `test_academic_requires_entity_match` |
| OECD "evidence" is a bare name mention in a catalogue page | `src/services/supplementary-evidence.js:266-279` | not carried (see 3.9) | none |
| Decay and certificate expiry read the wall clock | `src/services/time-decay.js:108, 129` | computed from the snapshot's `frozen_at`; rules have no clock | `test_replay_matches_stored_result` |
| Duplicate criterion lists in three files (handover P1) | `openai.js:13-40`, `supplementary-evidence.js:27-80`, `report-generator.js:956-963` | one manifest, generated code, CI grep for hand-typed codes | `test_no_hand_typed_codes_outside_generated_files` |

## 3. Not Carried Over

| Item | Legacy location | Reason |
|---|---|---|
| 3.1 Tier-based score uplift and multi-pillar bonus | `src/services/report-generator.js:1018` (midpoints 5, 15, 29, 35), `1205-1234`, `1452-1456` | Adds up to 43 points based on counts of URL slugs and phrases, not on evidence for any criterion. If calibration is wanted it must be a methodology change with a written rationale. |
| 3.2 Signal counting tiers and interpretation frames | `src/services/report-generator.js:269-461, 528-861, 977-1005, 1148-1201` | Counts of matched phrases are not evidence for a criterion (IC-08). The frames force narrative wording ("Developing or better") regardless of decisions. Reports are now rendered from stored decisions. |
| 3.3 Humaital-specific paths and patterns | `src/services/scraper.js:101-128`, `report-generator.js:379-411` | Tuned to Humaital's own site (`/rating-scoring`). A methodology for rating others must not carry site-specific boosts. |
| 3.4 Role upgrade by execution | `src/services/proof-of-execution.js:189-193` | Polarity is immutable (IC-01). Execution is its own column. |
| 3.5 Mail sending from the API process | `src/routes/send-report.js`, `src/services/mailer.js` | Reports are an API resource and webhooks notify subscribers. Mail belongs in a separate integration. Also the API received a browser-generated PDF with a browser-computed score. |
| 3.6 Log patching | `src/routes/log-patch.js`, `src/services/analysis-logger.js:152-213` | Results are computed only by the rules engine and stored append-only. |
| 3.7 Supabase REST client and `hai_analysis_logs` | `src/services/db.js`, `src/services/analysis-logger.js:67-143, 226-251` | Replaced by the ontology-generated PostgreSQL schema, the audit chain and the job queue. |
| 3.8 Wikipedia public-company heuristic | `src/services/supplementary-evidence.js:513-532` | A search snippet mentioning "NASDAQ" is not verification. CIK from SEC tickers with a domain match replaces it. |
| 3.9 OECD catalogue scrape | `src/services/supplementary-evidence.js:236-300` | Scrapes an HTML page with a regular expression and credits a mere name mention. No stable API. Left as a possible future connector row. |
| 3.10 GOVINFO and NIST_RMF sources | `negative-signal-overrides.js:66, 173`, `time-decay.js:37, 41`, `supplementary-evidence.js:99-101` | Referenced in constants but no fetcher exists. Their tier and decay values are kept as vocabulary attributes for when a connector is added. |
| 3.11 Warmup endpoint and diagnostic logging | `server.js:41-43, 95-119, 128-130` | Railway cold-start workarounds and temporary diagnostics. |
| 3.12 Memory caps for a 512 MB host | `src/routes/evaluate.js:234-244`, `supplementary-evidence.js:730-746` | Documents are stored in a blob store, not held in one string. |
| 3.13 `X-HAI-Secret` and body secret | `server.js:78-86` | Replaced by hashed API keys and JWTs with scopes. |
| 3.14 7-day dedupe returning HTTP 200 with `success: false` | `src/routes/evaluate.js:98-154` | Replaced by `Idempotency-Key` (same key returns the same assessment) and an explicit `/reassess`. Errors use HTTP status codes and the error envelope. |
| 3.15 Narrative generation by the model with pillar label floors | `src/services/report-generator.js:18-255, 1403-1569` | The report resource is built from decisions, evidence and coverage wording. An optional narrative provider may be added later as a reviewer copilot; it must not touch scores or statuses. |
| 3.16 Benchmark insert from client values | `src/routes/benchmark.js` | Peers are computed from stored results. |

## 4. The Console

The WordPress plugin and the browser-side scoring (section 2.11) are replaced by
`frontend/`, a React console that calls the API and renders stored values only.
It uses `frontend/src/generated/ontology.ts` for every code, label and allowed
review action, and contract tests check its connector list against
`config/connectors.yaml` and its review actions against the vocabulary. No
score, status or coverage wording is computed in the browser.
