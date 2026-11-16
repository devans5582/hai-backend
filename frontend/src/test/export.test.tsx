import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExportReportButton } from "../components/ExportReportButton";
import { renderWithProviders } from "./render";

const PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]); // %PDF-

function stubFetch(status = 200) {
  const fn = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (status !== 200) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: "organization has no assessment yet", details: {} } }), { status, headers: { "Content-Type": "application/json" } });
    }
    const name = url.includes("/organizations/") ? "HAI-Score-Acme-Corp-v3.pdf" : "HAI-Score-Acme-Corp-v1.pdf";
    return new Response(PDF, { status: 200, headers: { "Content-Type": "application/pdf", "Content-Disposition": `attachment; filename="${name}"` } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("ExportReportButton", () => {
  const clicks: string[] = [];
  beforeEach(() => {
    clicks.length = 0;
    localStorage.setItem("hai.session", "header.payload.signature");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:report"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.download);
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("downloads the assessment PDF with the session credentials and names the file as the API does", async () => {
    const fetchFn = stubFetch();
    renderWithProviders(<ExportReportButton assessmentId="11111111-1111-4111-8111-111111111111" subject="Acme Corp" />);
    await userEvent.click(screen.getByRole("button", { name: /Export PDF: report for Acme Corp/ }));
    await waitFor(() => expect(clicks).toEqual(["HAI-Score-Acme-Corp-v1.pdf"]));
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/v1/assessments/11111111-1111-4111-8111-111111111111/report.pdf");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer header.payload.signature");
    expect((init.headers as Record<string, string>).Accept).toBe("application/pdf");
    expect(await screen.findByRole("button", { name: /PDF downloaded/ })).toBeInTheDocument();
  });

  it("exports the latest version of an organization from a compact row button", async () => {
    const fetchFn = stubFetch();
    renderWithProviders(<ExportReportButton organizationId="22222222-2222-4222-8222-222222222222" subject="Acme Corp" compact />);
    await userEvent.click(screen.getByRole("button", { name: /Export PDF: report for Acme Corp/ }));
    await waitFor(() => expect(clicks).toEqual(["HAI-Score-Acme-Corp-v3.pdf"]));
    expect((fetchFn.mock.calls[0] as unknown as [string])[0]).toContain("/v1/organizations/22222222-2222-4222-8222-222222222222/report.pdf");
  });

  it("shows the API error instead of downloading when the export fails", async () => {
    stubFetch(404);
    renderWithProviders(<ExportReportButton organizationId="22222222-2222-4222-8222-222222222222" subject="Acme Corp" />);
    await userEvent.click(screen.getByRole("button", { name: /Export PDF/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("organization has no assessment yet");
    expect(clicks).toEqual([]);
  });

  it.each([
    ["text/html", "<html>Console</html>", "unexpected response"],
    ["application/pdf", "not a PDF", "invalid PDF"],
    ["application/pdf", "", "invalid PDF"],
  ])("rejects an invalid report with content type %s", async (contentType, body, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200, headers: { "Content-Type": contentType, "X-Request-Id": "bad-pdf-123" } })));
    renderWithProviders(<ExportReportButton assessmentId="assessment-1" subject="Acme Corp" />);
    await userEvent.click(screen.getByRole("button", { name: /Export PDF/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("alert")).toHaveTextContent("Support reference: bad-pdf-123");
    expect(clicks).toEqual([]);
  });

  it("shows a useful timeout error and support reference for an HTML proxy error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Gateway Timeout</html>", { status: 504, headers: { "X-Request-Id": "timeout-123" } })));
    renderWithProviders(<ExportReportButton assessmentId="assessment-1" subject="Acme Corp" />);
    await userEvent.click(screen.getByRole("button", { name: /Export PDF/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 504");
    expect(screen.getByRole("alert")).toHaveTextContent("Support reference: timeout-123");
    expect(clicks).toEqual([]);
  });
});
