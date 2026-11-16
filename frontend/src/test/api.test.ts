import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiRequestError } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

describe("API transport errors", () => {
  it("keeps HTTP status and request ID when the proxy returns HTML", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Bad Gateway</html>", {
      status: 502, headers: { "Content-Type": "text/html", "X-Request-Id": "proxy-request-123" },
    })));
    await expect(api.getAssessment("assessment-1")).rejects.toMatchObject({
      status: 502,
      code: "http_error",
      message: expect.stringContaining("temporarily unavailable (HTTP 502)"),
      details: { path: "/v1/assessments/assessment-1", request_id: "proxy-request-123" },
    });
  });

  it("retains structured API validation errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: {
      code: "validation_failed", message: "request validation failed", details: { fields: { website: "Invalid website" } },
    } }), { status: 422, headers: { "Content-Type": "application/json" } })));
    const error = await api.createAssessment({}, "retry-key").catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).fieldErrors).toEqual({ website: "Invalid website" });
  });

  it("rejects an HTML success response instead of treating it as assessment data", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Console</html>", { status: 200 })));
    await expect(api.getAssessment("assessment-1")).rejects.toMatchObject({ status: 200, code: "invalid_response" });
  });

  it("gives network failures a useful message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(api.health()).rejects.toMatchObject({ status: 0, code: "network_error", message: expect.stringContaining("Check your connection") });
  });

  it("drops the rejected session even if a 401 response is not JSON", async () => {
    localStorage.setItem("hai.session", "expired-session");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Unauthorized", { status: 401 })));
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(localStorage.getItem("hai.session")).toBeNull();
  });

  it("does not drop a fresh login when an older request returns 401", async () => {
    localStorage.setItem("hai.session", "old-session");
    let respond!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { respond = resolve; })));
    const pending = api.me();
    localStorage.setItem("hai.session", "new-session");
    respond(new Response("Unauthorized", { status: 401 }));
    await expect(pending).rejects.toMatchObject({ status: 401 });
    expect(localStorage.getItem("hai.session")).toBe("new-session");
  });
});
