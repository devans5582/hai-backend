import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Assessment } from "../lib/api";
import { Dashboard } from "../pages/Dashboard";
import { mockFetch, renderWithProviders } from "./render";

function assessment(id: string, domain: string, state: Assessment["lifecycle_state"], lifecycleLabel: string): Assessment {
  return {
    id,
    org_id: `org-${id}`,
    parent_assessment_id: null,
    requested_by: "api_key:test",
    submitted_domain: domain,
    direct_urls: [],
    stage_band: "growth",
    size_band: "mid",
    lifecycle_state: state,
    lifecycle_label: lifecycleLabel,
    certification_requested: false,
    failure_reason: state === "failed" ? "Source unavailable" : null,
    versions: { ontology: "1.0.0", methodology: "1.0.0", model: "test" },
    created_at: "2026-10-24T12:00:00Z",
    started_at: null,
    finished_at: null,
    links: {},
  };
}

const ASSESSMENTS = [
  assessment("11111111-1111-4111-8111-111111111111", "alpha.example", "completed_unverified", "Completed (unverified)"),
  assessment("22222222-2222-4222-8222-222222222222", "bravo.example", "acquiring", "Acquiring evidence"),
  assessment("33333333-3333-4333-8333-333333333333", "charlie.example", "failed", "Failed"),
  assessment("44444444-4444-4444-8444-444444444444", "delta.example", "awaiting_review", "Awaiting review"),
];

function overviewRow(name: string, domain: string, versions: number, state: Assessment["lifecycle_state"], lifecycleLabel: string, score: number | null, delta: number | null) {
  return {
    organization: { id: `org-${domain}`, display_name: name, legal_name: name, primary_domain: domain, industry_code: "technology", industry_label: "Technology", stage_band: "growth", size_band: "mid", identifiers_verified: false },
    versions,
    latest: { id: `latest-${domain}`, version: versions, lifecycle_state: state, lifecycle_label: lifecycleLabel, certification_requested: false, created_at: "2026-10-24T12:00:00Z", finished_at: null },
    result: score === null ? null : { hai_score: score, confidence_pct: 55, outcome_status: "certification_not_yet_achieved", outcome_label: "Certification not yet achieved" },
    previous: versions > 1 ? { id: "prev", created_at: "2026-09-01T00:00:00Z", hai_score: score === null || delta === null ? null : score - delta, outcome_status: null } : null,
    score_delta: delta,
  };
}

const OVERVIEW = [
  overviewRow("Alpha", "alpha.example", 3, "completed_unverified", "Completed (unverified)", 61.5, 4.5),
  overviewRow("Bravo", "bravo.example", 1, "acquiring", "Acquiring evidence", null, null),
];

function dashboardFetch() {
  return mockFetch((url) => {
    if (url === "/health") return { body: { status: "ok", ontology_version: "1.0.0", methodology_version: "1.0.0" } };
    if (url.startsWith("/v1/assessments?")) return { body: { items: ASSESSMENTS, total: ASSESSMENTS.length, limit: 50, offset: 0 } };
    if (url.startsWith("/v1/organizations/overview?")) return { body: { items: OVERVIEW, total: OVERVIEW.length, limit: 50, offset: 0 } };
    if (url.startsWith("/v1/reviews/tasks?")) return { body: { items: [], total: 0, limit: 50, offset: 0 } };
    return undefined;
  });
}

async function showAllRuns(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "All runs" }));
}

function visibleDomains() {
  return within(screen.getByRole("table")).getAllByRole("link", { name: /\.example/ }).filter((link) => !link.getAttribute("aria-label")).map((link) => link.textContent);
}

describe("Dashboard", () => {
  it("shows guests how to connect without requesting private assessments or review tasks", async () => {
    const { calls } = dashboardFetch();
    renderWithProviders(<Dashboard />);

    expect(screen.getByRole("heading", { name: "Your workspace starts here" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect your workspace" })).toHaveAttribute("href", "/login");
    expect(await screen.findByText("Operational")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(calls.map((call) => call.url)).toEqual(["/health"]);
  });

  it("filters lifecycle states and clears both filters and search after an empty match", async () => {
    localStorage.setItem("hai.apiKey", "hai_test.fake-key");
    dashboardFetch();
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);
    await showAllRuns(user);
    await screen.findByRole("link", { name: "View assessment for alpha.example" });

    await user.click(screen.getByRole("button", { name: "Completed" }));
    expect(visibleDomains()).toHaveLength(1);
    expect(visibleDomains()[0]).toContain("alpha.example");
    expect(screen.queryByRole("link", { name: "View assessment for bravo.example" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "In progress" }));
    expect(visibleDomains()).toHaveLength(2);
    expect(screen.getByRole("link", { name: "View assessment for bravo.example" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View assessment for delta.example" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View assessment for alpha.example" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Needs attention" }));
    expect(visibleDomains()).toHaveLength(2);
    expect(screen.getByRole("link", { name: "View assessment for charlie.example" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View assessment for delta.example" })).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "Search assessments" }), "alpha");
    expect(screen.getByRole("heading", { name: "No matching assessments" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByRole("searchbox", { name: "Search assessments" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(visibleDomains()).toHaveLength(4);
  });

  it("finds domains without case sensitivity and supports assessment IDs", async () => {
    localStorage.setItem("hai.apiKey", "hai_test.fake-key");
    const { calls } = dashboardFetch();
    const user = userEvent.setup();
    renderWithProviders(<Dashboard />);
    await showAllRuns(user);
    await screen.findByRole("link", { name: "View assessment for alpha.example" });
    const search = screen.getByRole("searchbox", { name: "Search assessments" });

    await user.type(search, "BRAVO");
    expect(visibleDomains()).toHaveLength(1);
    expect(screen.getByRole("link", { name: "View assessment for bravo.example" })).toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "33333333");
    expect(visibleDomains()).toHaveLength(1);
    expect(screen.getByRole("link", { name: "View assessment for charlie.example" })).toBeInTheDocument();
    expect(calls.some((call) => call.url === "/v1/assessments?limit=50&offset=0")).toBe(true);
    expect(calls.filter((call) => call.url.startsWith("/v1/assessments?")).every((call) => (call.init?.headers as Record<string, string>)["X-API-Key"] === "hai_test.fake-key")).toBe(true);
  });
});

describe("Dashboard folds assessments into organizations", () => {
  it("shows one row per organization with its latest version, score change and version count", async () => {
    localStorage.setItem("hai.apiKey", "hai_test.fake-key");
    const { calls } = dashboardFetch();
    renderWithProviders(<Dashboard />);
    expect(await screen.findByRole("link", { name: "View latest assessment for Alpha" })).toHaveAttribute("href", "/assessments/latest-alpha.example");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3); // header + two organizations, not four runs
    const alpha = screen.getByText("alpha.example · Technology").closest("tr") as HTMLElement;
    expect(within(alpha).getByText("v3")).toBeInTheDocument();
    expect(within(alpha).getByText("of 3")).toBeInTheDocument();
    expect(within(alpha).getByText("61.5")).toBeInTheDocument();
    expect(within(alpha).getByLabelText("change from previous version +4.5")).toHaveTextContent("+4.5");
    expect(within(alpha).getByText("Certification not yet achieved")).toBeInTheDocument();
    expect(within(alpha).getAllByRole("link")[0]).toHaveAttribute("href", "/organizations/org-alpha.example");
    const bravo = screen.getByText("bravo.example · Technology").closest("tr") as HTMLElement;
    expect(within(bravo).getByText("No result yet")).toBeInTheDocument();
    expect(screen.getByText("Organizations assessed")).toBeInTheDocument();
    // the grouped view asks the API for the fold; the console does not group runs itself
    expect(calls.some((c) => c.url.startsWith("/v1/organizations/overview?"))).toBe(true);
    expect(calls.some((c) => c.url.startsWith("/v1/assessments?"))).toBe(false);
  });
});
