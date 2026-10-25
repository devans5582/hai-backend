import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CoverageStrip, ScoreDial } from "../components/widgets";
import { AssessmentDetail } from "../pages/AssessmentDetail";
import { NewAssessment } from "../pages/NewAssessment";
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
  organization: { id: ASSESSMENT.org_id, name: "Acme Corp", legal_name: "Acme Corp", domain: "acme.example", industry_code: "Software" },
  result: { hai_score: 42.5, confidence_pct: 61.2, effectiveness: 25, outcome_status: "confidence_too_low", outcome_label: "Confidence too low", gate_reasons: ["confidence 61.2 below minimum 70"], review_triggers: [], caps_applied: [] },
  pillars: [
    { code: "TRU", name: "Trust", weight: 0.2, score: 50, confidence: 60, criteria_counted: 4, criteria_excluded: 0 },
    { code: "SAF", name: "Safety", weight: 0.15, score: 33.3, confidence: 70, criteria_counted: 2, criteria_excluded: 1 },
  ],
  criteria: [
    { code: "SAF-01", name: "Risk Mitigation", pillar: "SAF", definition: "d", content_status: "draft", level: 3, level_descriptor: "x", coverage_state: "observed", coverage_wording: "Assessed from admissible evidence.", confidence: 70, review_required: false, applied_rule_codes: ["GATE-COVERAGE"], evidence: [], decision_id: "d1" },
    { code: "SAF-02", name: "User Protection Mechanisms", pillar: "SAF", definition: "d", content_status: "draft", level: null, level_descriptor: null, coverage_state: "unavailable", coverage_wording: "Sources could not be reached. This is an access limitation, not a governance gap.", confidence: 0, review_required: false, applied_rule_codes: ["GATE-COVERAGE"], evidence: [], decision_id: "d2" },
  ],
  coverage_summary: { observed: 1, unavailable: 1 },
  connector_runs: [],
  sources: [],
  execution_notes: [],
  snapshot: { id: "s", frozen_at: "2026-10-24T12:05:00Z", sha256: "abc123def456abc123", links: 6 },
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
  it("shows the outcome status exactly as stored and opens the trace drawer", async () => {
    mockFetch((url) => {
      if (url.endsWith(`/v1/assessments/${ASSESSMENT.id}`)) return { body: ASSESSMENT };
      if (url.endsWith("/report")) return { body: REPORT };
      if (url.endsWith("/connector-runs")) return { body: { items: [], total: 0, limit: 1, offset: 0 } };
      if (url.includes("/v1/reviews/tasks")) return { body: { items: [], total: 0, limit: 50, offset: 0 } };
      if (url.endsWith("/trace/SAF-02")) return { body: { assessment_id: ASSESSMENT.id, criteria: [{ criterion_code: "SAF-02", criterion_name: "User Protection Mechanisms", decision_id: "d2", level: null, coverage_state: "unavailable", confidence: 0, applied_rule_codes: ["GATE-COVERAGE"], rules: [{ rule: "GATE-COVERAGE", before: { level: null }, after: { level: null }, note: "no admissible links and the primary sources could not be reached" }], inputs: {}, caps_applied: [], adjustments: [], finding: null, evidence: [] }] } };
      return undefined;
    });
    renderWithProviders(<AssessmentDetail />, { route: `/assessments/${ASSESSMENT.id}`, path: "/assessments/:id" });
    expect(await screen.findByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
    expect(screen.getByText("Confidence too low")).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Start assessment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("website must be a domain or URL");
    expect(screen.getByLabelText("Official website")).toHaveAttribute("aria-invalid", "true");
    const post = calls.find((c) => c.init?.method === "POST");
    const headers = post?.init?.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeTruthy();
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ organization_name: "Acme Corp", website: "nodomain", stage: "growth", size: "mid" });
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
