import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CoverageStrip, ScoreDial } from "../components/widgets";
import { AssessmentDetail } from "../pages/AssessmentDetail";
import { NewAssessment } from "../pages/NewAssessment";
import { OrganizationDetail } from "../pages/Organizations";
import { Reviews } from "../pages/Reviews";
import { Verify } from "../pages/Verify";
import { mockFetch, renderWithProviders } from "./render";

const ASSESSMENT = {
  id: "11111111-1111-4111-8111-111111111111",
  org_id: "22222222-2222-4222-8222-222222222222",
  parent_assessment_id: null,
  requested_by: "api_key:partner",
  submitted_domain: "acme.example",
  direct_urls: [],
  stage_band: "growth",
  size_band: "mid",
  lifecycle_state: "completed_unverified",
  lifecycle_label: "Completed (unverified)",
  certification_requested: false,
  failure_reason: null,
  versions: { ontology: "1.0.0", methodology: "1.0.0", ruleset: "1.0.0", prompt: "1.0.0", model: "heuristic:ladder-1" },
  created_at: "2026-10-24T12:00:00Z",
  started_at: null,
  finished_at: null,
  links: {},
};

const REPORT = {
  product: { report_name: "HAI Score", long_name: "Human Alignment Index" },
  assessment: { id: ASSESSMENT.id, lifecycle_state: "completed_unverified", versions: ASSESSMENT.versions },
  organization: { id: ASSESSMENT.org_id, name: "Acme Corp", legal_name: "Acme Corp", domain: "acme.example", industry_code: "technology" },
  result: { hai_score: 42.5, confidence_pct: 61.2, effectiveness: 25, outcome_status: "confidence_too_low", outcome_label: "Confidence too low", gate_reasons: ["confidence 61.2 below minimum 70"], review_triggers: [], caps_applied: [] },
  pillars: [
    { code: "TRU", name: "Trust", weight: 0.2, score: 50, confidence: 60, criteria_counted: 4, criteria_excluded: 0, status: "developing", status_label: "Developing", status_wording: "Evidence exists at policy level but lacks execution proof." },
    { code: "SAF", name: "Safety", weight: 0.15, score: 33.3, confidence: 70, criteria_counted: 2, criteria_excluded: 1, status: "progressing", status_label: "Progressing", status_wording: "Policy and partial execution evidence present; gaps remain." },
  ],
  criteria: [
    { code: "SAF-01", name: "Risk Mitigation", pillar: "SAF", definition: "d", content_status: "draft", level: 3, level_descriptor: "x", coverage_state: "observed", coverage_wording: "Assessed from admissible evidence.", confidence: 70, review_required: false, applied_rule_codes: ["GATE-COVERAGE"], evidence: [], evidence_basis: {}, best_rung: null, focus_areas: [], confidence_components: {}, decision_id: "d1" },
    { code: "SAF-02", name: "User Protection Mechanisms", pillar: "SAF", definition: "d", content_status: "draft", level: null, level_descriptor: null, coverage_state: "unavailable", coverage_wording: "Sources could not be reached. This is an access limitation, not a governance gap.", confidence: 0, review_required: false, applied_rule_codes: ["GATE-COVERAGE"], evidence: [], decision_id: "d2" },
  ],
  coverage_summary: { observed: 1, unavailable: 1 },
  connector_runs: [],
  sources: [],
  execution_notes: [],
  snapshot: { id: "s", frozen_at: "2026-10-24T12:05:00Z", sha256: "abc123def456abc123", links: 6 },
  evidence_basis: { by_rung: { none: 0, stated_commitment: 1, specified_control: 0, documented_execution: 1, independently_verified: 0 }, labels: { none: "None", stated_commitment: "Stated commitment", specified_control: "Specified control", documented_execution: "Documented execution", independently_verified: "Independently verified" }, criteria_counted: 2 },
  evidence_strength: { core_governance: { label: "Core governance", criteria_with_evidence: 1, share: 0.5, strength: "Emerging" } },
  focus_areas: [{ code: "control_verification", label: "Verification of AI controls", question: "Do the controls work?", cross_cutting: false, criteria: ["SAF-01"], links: 1, by_rung: {}, best_rung: "documented_execution", best_rung_label: "Documented execution" }],
  verification: { controls: [], tests_by_method: {}, threats_exercised: {}, ai_systems: [], controls_with_unexercised_capabilities: 0 },
  incident_response: [],
  impact_measures: { items: [], by_kind: {}, demonstrated_benefit: 0, total: 0 },
  confidence_methodology: { model: "components", source: "HAI Report", weights: { source_credibility: 0.4, evidence_type: 0.3, cross_source_validation: 0.2, recency: 0.1 }, evidence_type_credit: {} },
  drafts_notice: "Criterion definitions marked draft are placeholders.",
};

describe("ScoreDial and CoverageStrip", () => {
  it("renders the stored score and an accessible label", () => {
    renderWithProviders(<ScoreDial score={42.5} />);
    expect(screen.getByRole("img", { name: "HAI Score: 42.5 out of 100" })).toBeInTheDocument();
    renderWithProviders(<ScoreDial score={null} />);
    expect(screen.getByRole("img", { name: "HAI Score: n/a out of 100" })).toBeInTheDocument();
  });
  it("names every coverage cell and reports selection", async () => {
    const picked: string[] = [];
    renderWithProviders(<CoverageStrip cells={[{ code: "SAF-01", name: "Risk Mitigation", coverage_state: "observed", level: 3 }, { code: "IMP-04", name: "Durability", coverage_state: "unavailable", level: null }]} onSelect={(c) => picked.push(c)} />);
    const cell = screen.getByRole("listitem", { name: /IMP-04 Durability: Unavailable/ });
    await userEvent.click(cell);
    expect(picked).toEqual(["IMP-04"]);
  });
});

describe("AssessmentDetail", () => {
  it("opens the new run after reassessment and clears the previous score, tab and export error", async () => {
    const next = { ...ASSESSMENT, id: "99999999-9999-4999-8999-999999999999", parent_assessment_id: ASSESSMENT.id, lifecycle_state: "queued", lifecycle_label: "Queued" };
    const { calls } = mockFetch((url, init) => {
      if (url.endsWith(`/v1/assessments/${ASSESSMENT.id}/reassess`) && init?.method === "POST") return { status: 202, body: next };
      if (url.endsWith(`/v1/assessments/${ASSESSMENT.id}`)) return { body: ASSESSMENT };
      if (url.endsWith(`/v1/assessments/${next.id}`)) return { body: next };
      if (url.endsWith(`/v1/assessments/${ASSESSMENT.id}/report`)) return { body: REPORT };
      if (url.endsWith(`/v1/assessments/${next.id}/report`)) return { body: { ...REPORT, assessment: { ...REPORT.assessment, id: next.id, lifecycle_state: "queued" }, result: null, pillars: [], criteria: [] } };
      if (url.endsWith("/report.pdf")) return { status: 409, body: { error: { code: "conflict", message: url.includes(next.id) ? "new report is not ready" : "previous report download failed", details: {} } } };
      if (url.endsWith("/connector-runs") || url.includes("/v1/reviews/tasks") || url.endsWith("/history")) return { body: { items: [], total: 0, limit: 50, offset: 0 } };
      return undefined;
    });
    renderWithProviders(<AssessmentDetail />, { route: `/assessments/${ASSESSMENT.id}`, path: "/assessments/:id" });
    expect(await screen.findByRole("img", { name: "HAI Score: 42.5 out of 100" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Export PDF: report for Acme Corp" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("previous report download failed");
    await userEvent.click(screen.getByRole("tab", { name: "Criteria" }));
    await userEvent.click(screen.getByRole("button", { name: "Reassess" }));
    expect(await screen.findByText("Your assessment is in the queue. Evidence collection will begin when a worker is available.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("img", { name: "HAI Score: n/a out of 100" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "HAI Score: 42.5 out of 100" })).not.toBeInTheDocument();
    expect(screen.queryByText(/previous report download failed/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Export PDF: report for Acme Corp" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("new report is not ready");
    expect(calls.some((call) => call.url.endsWith(`/v1/assessments/${next.id}/report.pdf`))).toBe(true);
  });

  it("renders recorded calibration and baseline pillars without recalculating the stored score", async () => {
    mockFetch((url) => {
      if (url.endsWith(`/v1/assessments/${ASSESSMENT.id}`)) return { body: ASSESSMENT };
      if (url.endsWith("/report")) return { body: {
        ...REPORT,
        result: { ...REPORT.result, hai_score: 56.3, calibration: { baseline_score: 12.5, multiplier: 4.5, calibrated_score: 56.3, cap: 100, certification_basis: "baseline", pillar_basis: "baseline", threshold: 65 } },
      } };
      if (url.endsWith("/connector-runs") || url.includes("/v1/reviews/tasks") || url.endsWith("/history")) return { body: { items: [], total: 0, limit: 50, offset: 0 } };
      return undefined;
    });
    renderWithProviders(<AssessmentDetail />, { route: `/assessments/${ASSESSMENT.id}`, path: "/assessments/:id" });
    expect(await screen.findByRole("img", { name: "HAI Score: 56.3 out of 100" })).toBeInTheDocument();
    expect(screen.getByLabelText("Score calibration")).toHaveTextContent("Calibration: 4.5x; baseline 12.5/100; displayed 56.3/100.");
    expect(screen.getByLabelText("Score calibration")).toHaveTextContent("Certification uses the baseline score (minimum 65.0/100)");
    expect(screen.getByText("Pillar scores use the baseline scale before overall score calibration.")).toBeInTheDocument();
    expect(screen.getByText("Confidence too low")).toBeInTheDocument();
  });

  it("explains an unavailable score using the report's stored reason", async () => {
    mockFetch((url) => {
      if (url.endsWith(`/v1/assessments/${ASSESSMENT.id}`)) return { body: ASSESSMENT };
      if (url.endsWith("/report")) return { body: {
        ...REPORT,
        result: { ...REPORT.result, hai_score: null },
        score_availability: { code: "sources_unavailable", message: "No criteria could be scored because the evidence sources were unavailable." },
      } };
      if (url.endsWith("/connector-runs") || url.includes("/v1/reviews/tasks") || url.endsWith("/history")) return { body: { items: [], total: 0, limit: 50, offset: 0 } };
      return undefined;
    });
    renderWithProviders(<AssessmentDetail />, { route: `/assessments/${ASSESSMENT.id}`, path: "/assessments/:id" });
    expect(await screen.findByText("No criteria could be scored because the evidence sources were unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "HAI Score: n/a out of 100" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Score calibration")).not.toBeInTheDocument();
  });

  it("shows the outcome status exactly as stored and opens the trace drawer", async () => {
    mockFetch((url) => {
      if (url.endsWith(`/v1/assessments/${ASSESSMENT.id}`)) return { body: ASSESSMENT };
      if (url.endsWith("/report")) return { body: REPORT };
      if (url.endsWith("/connector-runs")) return { body: { items: [], total: 0, limit: 1, offset: 0 } };
      if (url.includes("/v1/reviews/tasks")) return { body: { items: [], total: 0, limit: 50, offset: 0 } };
      if (url.endsWith(`/v1/organizations/${ASSESSMENT.org_id}/history`)) return { body: { organization_id: ASSESSMENT.org_id, latest_id: "99999999-9999-4999-8999-999999999999", total: 2, items: [{ version: 2, is_latest: true, assessment: { id: "99999999-9999-4999-8999-999999999999", lifecycle_state: "queued", lifecycle_label: "Queued", created_at: "2026-10-25T12:00:00Z", finished_at: null, requested_by: "x", methodology_version: "2.0.0", ruleset_version: "1.1.0", model_id: "m", parent_assessment_id: ASSESSMENT.id, certification_requested: false }, result: null }, { version: 1, is_latest: false, assessment: { id: ASSESSMENT.id, lifecycle_state: "completed_unverified", lifecycle_label: "Completed (unverified)", created_at: ASSESSMENT.created_at, finished_at: null, requested_by: "x", methodology_version: "1.0.0", ruleset_version: "1.0.0", model_id: "m", parent_assessment_id: null, certification_requested: false }, result: { hai_score: 42.5, confidence_pct: 61.2, outcome_status: "confidence_too_low", outcome_label: "Confidence too low" } }] } };
      if (url.endsWith("/trace/SAF-02")) return { body: { assessment_id: ASSESSMENT.id, criteria: [{ criterion_code: "SAF-02", criterion_name: "User Protection Mechanisms", decision_id: "d2", level: null, coverage_state: "unavailable", confidence: 0, applied_rule_codes: ["GATE-COVERAGE"], rules: [{ rule: "GATE-COVERAGE", before: { level: null }, after: { level: null }, note: "no admissible links and the primary sources could not be reached" }], inputs: {}, caps_applied: [], adjustments: [], finding: null, evidence: [] }] } };
      return undefined;
    });
    renderWithProviders(<AssessmentDetail />, { route: `/assessments/${ASSESSMENT.id}`, path: "/assessments/:id" });
    expect(await screen.findByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
    expect(screen.getByText("Confidence too low")).toBeInTheDocument();
    // an earlier version says so and points at the latest one
    expect(await screen.findByText("Assessment version 1 of 2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the latest version" })).toHaveAttribute("href", "/assessments/99999999-9999-4999-8999-999999999999");
    expect(screen.getByRole("img", { name: "HAI Score: 42.5 out of 100" })).toBeInTheDocument();
    expect(screen.getByText(/Confidence 61.2/)).toBeInTheDocument();
    // the console never computes: the unavailable criterion is shown with its stored wording, not a zero
    await userEvent.click(screen.getByRole("tab", { name: "Criteria" }));
    const row = screen.getByText("User Protection Mechanisms").closest("tr") as HTMLElement;
    expect(within(row).getByText("n/a")).toBeInTheDocument();
    expect(within(row).getByText(/access limitation/)).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Open trace for SAF-02" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/primary sources could not be reached/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Close trace" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("NewAssessment", () => {
  it("maps server validation errors to fields and sends an Idempotency-Key", async () => {
    const { calls } = mockFetch((url, init) => {
      if (url.endsWith("/v1/assessments") && init?.method === "POST") {
        return { status: 422, body: { error: { code: "validation_failed", message: "request validation failed", details: { fields: { website: "website must be a domain or URL" } } } } };
      }
      return undefined;
    });
    renderWithProviders(<NewAssessment />, { route: "/assessments/new", path: "/assessments/new" });
    await userEvent.type(screen.getByLabelText("Organization name"), "Acme Corp");
    await userEvent.type(screen.getByLabelText("Official website"), "nodomain");
    // industry is required and offered as the vocabulary's twelve categories
    await userEvent.click(screen.getByRole("button", { name: "Start assessment" }));
    expect(screen.getByText("Choose an industry.")).toBeInTheDocument();
    expect(calls.some((c) => c.init?.method === "POST")).toBe(false);
    const industry = screen.getByLabelText("Industry") as HTMLSelectElement;
    expect(Array.from(industry.options).map((o) => o.textContent)).toEqual(["Choose an industry", "Education", "Energy", "Financial Services", "Government", "Healthcare", "Hospitality", "Manufacturing", "Professional Services", "Retail", "Technology", "Travel", "Other"]);
    await userEvent.selectOptions(industry, "technology");
    await userEvent.click(screen.getByRole("button", { name: "Start assessment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("website must be a domain or URL");
    expect(screen.getByLabelText("Official website")).toHaveAttribute("aria-invalid", "true");
    const post = calls.find((c) => c.init?.method === "POST");
    const headers = post?.init?.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ organization_name: "Acme Corp", website: "nodomain", stage: "growth", size: "mid", industry: "technology" });
  });
});

describe("OrganizationDetail", () => {
  it("distinguishes the current result from a newer pending run in history", async () => {
    const nextId = "99999999-9999-4999-8999-999999999999";
    mockFetch((url) => {
      if (url.endsWith(`/v1/organizations/${ASSESSMENT.org_id}`)) return { body: { id: ASSESSMENT.org_id, display_name: "Acme Corp", legal_name: "Acme Corp", primary_domain: "acme.example", industry_code: "technology", identifiers_verified: false, entity_confidence: null } };
      if (url.endsWith("/history")) return { body: { organization_id: ASSESSMENT.org_id, latest_id: nextId, current_id: ASSESSMENT.id, total: 2, items: [
        { version: 2, is_latest: true, is_current: false, assessment: { ...ASSESSMENT, id: nextId, lifecycle_state: "queued", lifecycle_label: "Queued", methodology_version: "1.0.0", ruleset_version: "1.0.0" }, result: null },
        { version: 1, is_latest: false, is_current: true, assessment: { ...ASSESSMENT, methodology_version: "1.0.0", ruleset_version: "1.0.0" }, result: REPORT.result },
      ] } };
      if (url.includes("/evidence")) return { body: { items: [], total: 0, limit: 20, offset: 0 } };
      return undefined;
    });
    renderWithProviders(<OrganizationDetail />, { route: `/organizations/${ASSESSMENT.org_id}`, path: "/organizations/:id" });
    const current = await screen.findByRole("link", { name: /v1\s*Current result/ });
    expect(current).toHaveAttribute("href", `/assessments/${ASSESSMENT.id}`);
    expect(screen.getByRole("link", { name: /v2\s*Latest run/ })).toHaveAttribute("href", `/assessments/${nextId}`);
    expect(screen.getByRole("button", { name: "Export PDF: report for Acme Corp (current result)" })).toBeInTheDocument();
    expect(screen.getByText(/Each new result replaces the current report when ready/)).toBeInTheDocument();
  });
});

describe("Reviews", () => {
  it("offers only the actions allowed for the subject type and requires a reason", async () => {
    localStorage.setItem("hai.reviewerToken", "x." + btoa(JSON.stringify({ sub: "rev-1", role: "reviewer", scopes: [] })) + ".y");
    const { calls } = mockFetch((url, init) => {
      if (url.includes("/v1/reviews/tasks")) return { body: { items: [{ id: "t1", assessment_id: ASSESSMENT.id, subject_type: "incident", subject_id: "i1", reason: "unverified incident", status: "open", opened_by: "service:worker", excluded_reviewers: [], allowed_actions: ["substantiate", "dismiss", "escalate"], closed_by: null, closed_at: null, created_at: "2026-10-24T12:00:00Z", updated_at: "2026-10-24T12:00:00Z" }], total: 1, limit: 50, offset: 0 } };
      if (url.endsWith("/v1/reviews") && init?.method === "POST") return { status: 201, body: { review: {}, task: { status: "closed" }, finalize_queued: true } };
      return undefined;
    });
    renderWithProviders(<Reviews />, { route: "/reviews", path: "/reviews" });
    expect(await screen.findByRole("heading", { name: "Incident" })).toBeInTheDocument();
    const select = screen.getByLabelText("Action") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value).sort()).toEqual(["dismiss", "escalate", "substantiate"]);
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason (required)"), "not this organization");
    await userEvent.selectOptions(select, "dismiss");
    await userEvent.click(submit);
    expect(await screen.findByRole("status")).toHaveTextContent("Task is now closed. Finalize queued.");
    const post = calls.find((c) => c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ task_id: "t1", action: "dismiss", reason: "not this organization" });
    expect((post?.init?.headers as Record<string, string>)["Authorization"]).toMatch(/^Bearer /);
  });
});

describe("Verify", () => {
  it("discloses recorded calibration and the baseline certification threshold", async () => {
    mockFetch((url) => url.includes("/v1/certifications/HAI-CAL/verify") ? { body: {
      valid: true, status: "valid", certificate_number: "HAI-CAL", organization: "Acme Corp", hai_score: 100,
      signed_at: "2026-10-24T12:00:00Z", expires_at: null, reviewer: "rev-1", methodology_version: "4.0.0",
      calibration: { baseline_score: 81.5, multiplier: 4.5, calibrated_score: 100, cap: 100, certification_basis: "baseline", pillar_basis: "baseline", threshold: 70 },
    } } : undefined);
    renderWithProviders(<Verify />, { route: "/verify?number=HAI-CAL", path: "/verify" });
    const note = await screen.findByLabelText("Score calibration");
    expect(note).toHaveTextContent("baseline 81.5/100; displayed 100.0/100");
    expect(note).toHaveTextContent("Certification uses the baseline score (minimum 70.0/100)");
  });

  it("shows a valid certificate and a not-found message", async () => {
    mockFetch((url) => {
      if (url.includes("/v1/certifications/HAI-OK/verify")) return { body: { valid: true, status: "valid", certificate_number: "HAI-OK", organization: "Acme Corp", hai_score: 81.5, signed_at: "2026-10-24T12:00:00Z", expires_at: "2027-10-24T12:00:00Z", reviewer: "rev-1", methodology_version: "1.0.0" } };
      if (url.includes("/v1/certifications/HAI-NO/verify")) return { status: 404, body: { error: { code: "not_found", message: "no certificate", details: {} } } };
      return undefined;
    });
    renderWithProviders(<Verify />, { route: "/verify?number=HAI-OK", path: "/verify" });
    expect(await screen.findByText("Valid")).toBeInTheDocument();
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    renderWithProviders(<Verify />, { route: "/verify?number=HAI-NO", path: "/verify" });
    expect(await screen.findByRole("alert")).toHaveTextContent("No certificate with that number.");
  });
});
