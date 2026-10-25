import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

export function renderWithProviders(ui: ReactElement, { route = "/", path = "/", ...options }: RenderOptions & { route?: string; path?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="*" element={<div data-testid="elsewhere">elsewhere</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
    options,
  );
}

export type FetchRoute = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined;

/** Stub global fetch with a router over path prefixes. Unmatched calls return 404 envelopes. */
export function mockFetch(route: FetchRoute) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    calls.push({ url, init });
    const matched = route(url, init) ?? { status: 404, body: { error: { code: "not_found", message: "no route", details: {} } } };
    const status = matched.status ?? 200;
    const text = matched.body === undefined ? "" : JSON.stringify(matched.body);
    return new Response(text, { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}
