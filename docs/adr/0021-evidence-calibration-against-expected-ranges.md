# Evidence Calibration Against Expected Ranges

Date: 2026-11-22

Status: Accepted implementation; methodology content remains draft.

## Request And Evidence

The owner supplied a sheet of 22 organizations with the score the platform
displayed and the range Humaital expects for each ("Metrics Score vs Ground
Truth"), and asked for the system to be calibrated so that observed scores
match and a new organization lands where it should.

Under methodology 5.0.0 the sheet shows 2 of 22 inside their range, 8 with no
score, and 2 at 100. Re-running the same organizations through the unchanged
job chain reproduced those results (Accenture 12.5, MIT 5.5, Pfizer 51.5,
Roche 30.0, Microsoft 100, Chevron 100). The reproduction, and every number
below, comes from `tests/calibration/harness.py`, which runs the real
pipeline against a throwaway database and replays cached HTTP responses.

Reading what each run collected gave four causes. None of them is the
criterion curve.

1. **Collection.** The page budget went to pages that matched a keyword and
   carried no governance content: store locations, return policies, product
   listings, 1996 press releases, the same page under 30 country parameters.
   A site with flat URLs was cut off after six pages. Eight organizations
   returned nothing because the submitted domain refused the crawler or
   served an empty JavaScript shell, and no other source was tried in
   earnest.
2. **Identity.** Entity resolution has never succeeded in production:
   Wikidata's robots.txt disallows the API path and the fetcher honours it.
   Without a verified CIK, SEC retrieval fell back to matching any filer
   whose name contained the organization's words. "Harvard" collected
   Harvard Bioscience, "Marriott" collected Marriott Vacations Worldwide and
   "Hilton" collected Hilton Grand Vacations. Where the right filer was
   found, the newest filings mentioning AI were earnings releases.
3. **Recognition.** Retrieval hints and lexicons were narrow enough that
   most governance statements were classified neutral. Accenture produced
   105 neutral links and 6 supporting ones from 21 pages.
4. **The multiplier.** A baseline of 20 or more became 100. With most
   criteria unavailable, the remaining weights were renormalised, so one
   level-3 criterion produced 50 and then 100.

## Decision

Remove the overall multiplier and make the evidence path good enough that
the evidence-derived score is the displayed score.

### Scoring

* `scoring.calibration.multiplier` is 1.0. The mechanism stays so that 4.0.0
  and 5.0.0 results can be replayed with their own manifests.
* `scoring.corroboration` requires two separate passages before the ladder
  credits a specified control or documented execution (decision D15).
* `outcome.withhold_score_without_coverage`: an access-limited assessment,
  or one with fewer than four counted criteria, publishes no overall score
  (decision D16).
* The criterion curve, pillar weights, materiality weights, the missing
  level, confidence and certification are unchanged.

### What Counts As Evidence

* General corporate governance (a code of conduct, a board committee, a
  privacy programme) is admitted for the criterion it speaks to and can earn
  stated commitment and specified control. Documented execution and
  independent verification must be about the organization's AI practice
  (decision D14). Before 6.0.0 this check covered the Safety pillar only.
* A specified control is an accountable party beside a defined procedure.
  The organization speaking for itself ("we review every release") is an
  accountable party, following the published definition of documented
  controls: defined procedures, assigned responsibilities and established
  safeguards.
* A record of execution is a result beside a date or a quantity, in the
  organization's own voice.
* Guards in `lexicons.evidence_quality` keep keyword accidents out: running
  prose of at least eight words, the criterion's vocabulary in the quote
  itself, owner beside procedure, date beside result, no quotation of
  another party, and no risk-factor language. These were written after
  reading the false positives: a director's biography mentioning an AI
  company, a proxy table row, another firm's chief executive quoted in a
  press release, and "could adversely affect" sentences from a 10-K were all
  being credited.
* Retrieval hints gained general governance vocabulary for every criterion.
  Hints are retrieval terms, not methodology content, and stay draft.

### Collection

* The crawler ranks links before it fetches them: AI governance, then
  governance, then general company pages; storefront, career, help and news
  pages drop three ranks; a link matching more governance terms goes first.
  No section of a site takes more than six pages. Query-string variants of
  one page are fetched once. Paths filed under a year older than the
  freshness window are skipped.
* Sitemaps, the organization's corporate and governance hosts
  (`corporate.`, `about.`, `investor.`, `policies.` and others) and an
  English edition of a site that answers in another language are read.
  A governance report linked from those pages but hosted on another domain
  is fetched as the organization's own disclosure (PDF only, never a
  regulator, standards body, journal, audit firm or archive).
* A small site is read in full while budget remains.
* The document size limit is 12 MB; long PDFs are read to 200 pages.
* SEC filings: the registrant is the verified CIK, else the filer whose
  annual report cites the submitted domain as its own website, else the one
  filer whose name equals the organization's. The connector then fetches the
  newest proxy statement and annual report from the submissions index.
* When the organization's site yields fewer than three documents, the
  Internet Archive's recent captures are crawled in its place, each document
  marked as an archived copy with its capture date.

### What Was Not Done

* The crawler still identifies itself as `HAI-Assessment-Bot` and still
  honours robots.txt. A site that returns 403 to it is not read by
  pretending to be a browser.
* Wikidata is still not queried in practice, because its robots.txt
  disallows the API and SPARQL paths. The domain-first resolver is
  implemented and tested against the fake internet; enabling it is the
  owner's decision on whether a documented data API is governed by its own
  terms or by robots.txt.
* No organization, industry or size receives a prior. Nothing reads the
  expected ranges except the harness that prints the comparison.
* No criterion definition, level descriptor or weight was written or
  changed.

## Result

The 22 organizations were assessed through the real pipeline on 2026-11-22
under methodology 6.0.0 with the heuristic provider. The README carries the
full table; `make calibrate` reproduces it.

| | 5.0.0 Rerun | 6.0.0 |
|---|---:|---:|
| Inside the expected range | 2 | 13 |
| Within 3 points of it | 1 | 4 |
| Further out | 12 | 5 |
| No score | 7 | 0 |
| Displayed 100 (counted in further out) | 2 | 0 |

The 5.0.0 column is the same set re-run on the same day under the previous
methodology. The owner's sheet, crawled earlier, shows 8 without a score.

* Every organization is assessed, including the eight that had no score. PwC,
  Goldman Sachs, Marriott and Chevron still refuse the crawler; their scores
  rest on archived captures and, where they are registrants, SEC filings, and
  the report says so.
* Organizations with ordinary governance and a readable public record land
  between 47.7 and 52.9, inside their expected ranges (Costco, Walmart, Home
  Depot, AA, Delta, Hilton, Marriott, Chevron, Shell, Pfizer, Roche, Meta).
* Level 4 was reached on 4 criteria for Microsoft, 3 for Accenture, 2 for
  Home Depot and MIT and 1 for Walmart and Siemens, each from two or more
  passages recording AI practice.
* Outside by less than 3 points: Accenture 54.0 (expected from 55), Harvard
  39.1 (from 40), Siemens 47.4 (from 50) and Foxconn 46.1 (up to 45).
* Outside by more: Goldman Sachs 50.0 (from 55), PwC 47.7 (from 55), Fidelity
  42.6 (from 50), Microsoft 55.1 (from 65) and Humaital 40.0 (from 65).

The instrument has limits that calibration does not remove, and they are
recorded here so that nobody reads more into a score than it holds.

* **It reads with lexicons.** A level-3 score on every criterion says that
  the organization's public record describes controls for every topic. It
  does not say the controls are good. Most large organizations reach that
  level, so twelve of the 22 score exactly or almost exactly 50. An expected
  range that straddles 50 is met; that is agreement, not fine
  discrimination. Foxconn, expected lower than its peers, is not separated
  from them.
* **The upper ranges need evidence that is seldom public in a form lexicons
  can read.** Reaching 55 or 65 requires documented AI execution on most
  criteria. Where such records were collected they were credited; for most
  organizations they were not found. Which pages a bounded crawl reaches
  also matters: one run collected Meta's published model safety reports and
  scored it 59.3, the final run did not and scored it 50.0. The remaining
  independent sources (news, scholarly search, the certificate registry) are
  blocked, rate limited or unconfigured, so level 5 is not reachable today.
* **Humaital's own range is not met.** It is expected at 65 to 75 and scores
  40.0 from 20 pages. Its site describes a methodology and assigns
  oversight; it holds few records of operation. The Phase 6 service carried
  boosts specific to Humaital's site and they were deliberately not ported.
  The 63.5 it displayed under 5.0.0 was a baseline of 12.7 multiplied by 5.
* **The set was used to write the vocabulary.** Agreement on these 22
  overstates agreement on an organization nobody has looked at.
* **An assessment is slower.** More documents and links take about two
  minutes for one organization, up from under one.

Three things would move the instrument further, in order of effect: a model
provider for the evaluation step (the rules already cap a model's proposal
by the evidence ladder, so a model can only remove false credit), Humaital's
canonical level descriptors, and evidence supplied by the organization
(direct URLs and uploads are already supported).

## A Check On Organizations Outside The Set

Eight organizations that are not in the sheet, and were not looked at while
the vocabulary and retrieval were written, were run once through the same
pipeline. They have no expected range from Humaital; each is compared with
the ranges the sheet gives its industry peers, which is an analogy and not
ground truth.

| Organization | Peer Range Used | 6.0.0 | Against Peer Range | Documents | Website |
|---|---|---:|---|---:|---|
| IBM | 50 to 80 (Microsoft, Meta) | 52.7 | in range | 44 | succeeded |
| JPMorgan Chase | 50 to 75 (Fidelity, Goldman Sachs) | 50.0 | in range | 45 | succeeded |
| Johnson & Johnson | 50 to 70 (Pfizer, Roche) | 50.0 | in range | 40 | succeeded |
| Stanford University | 40 to 65 (MIT, Harvard) | 46.0 | in range | 43 | succeeded |
| Target | 35 to 60 (Costco, Home Depot, Walmart) | 48.6 | in range | 34 | succeeded |
| United Airlines | 35 to 55 (AA, Delta) | 50.0 | in range | 33 | blocked |
| Deloitte | 55 to 70 (Accenture, PwC) | 44.9 | -10.1 | 33 | succeeded |
| BP | 40 to 60 (Shell, Chevron) | 32.5 | -7.5 | 8 | blocked |

The pattern is the one seen on the set: a readable public record gives about
50, a peer range that starts at 55 is not reached, and an organization whose
site refuses the crawler and leaves few archived pages scores low for lack of
evidence, not for lack of governance.

## Versioning And History

Methodology 6.0.0 and ruleset 5.0.0 under ontology 1.3.0. Migration
`0010_methodology_6.sql` updates the version metadata. Stored results keep
their pins; an assessment made under 5.0.0 still shows its multiplier and is
not rescored. Reassess an organization to obtain a 6.0.0 result. Benchmarks
remain within one version cohort.

## Validation

Unit tests cover link ranking, the section cap, query variants, dated
paths, off-site reports, the English edition, the archive fallback, the
registrant checks, the guards, corroboration, the withheld score and the
control-byte fix. `make calibrate` runs the 22 organizations and exits
non-zero while any is outside its range. PostgreSQL suites run with roles
enabled and disabled.
