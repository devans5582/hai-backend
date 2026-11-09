// Sign-in, sign-up, the auth gate, role-based navigation and the invitation flow.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";
import type { Me } from "../lib/api";
import { mockFetch } from "./render";

const ROLES: Me["roles"] = {
  roles: [
    { code: "owner", label: "Platform owner", description: "Everything.", account_kind: "platform", scopes: ["admin"], narrowable: false },
    { code: "reviewer", label: "Reviewer", description: "Reviews.", account_kind: "platform", scopes: ["assessments:read", "organizations:read", "reviews:write", "certification:sign", "ontology:read", "audit:read"], narrowable: true },
    { code: "viewer", label: "Viewer", description: "Reads.", account_kind: "platform", scopes: ["assessments:read", "organizations:read", "ontology:read"], narrowable: true },
    { code: "org_member", label: "Organization member", description: "Sees reports.", account_kind: "organization", scopes: ["assessments:read", "organizations:read", "ontology:read"], narrowable: true },
  ],
  scopes: [
    { code: "assessments:read", label: "View assessments", description: "Read." },
    { code: "assessments:write", label: "Start assessments", description: "Create." },
    { code: "organizations:read", label: "View organizations", description: "Read." },
    { code: "reviews:write", label: "Review queue", description: "Act." },
    { code: "certification:sign", label: "Sign certifications", description: "Sign." },
    { code: "ontology:read", label: "Methodology", description: "Read." },
    { code: "audit:read", label: "Audit log", description: "Read." },
    { code: "admin", label: "Administration", description: "All." },
  ],
};

function meFor(role: string, kind: "platform" | "organization"): Me {
  const spec = ROLES.roles.find((r) => r.code === role)!;
  const admin = spec.scopes.includes("admin");
  return {
    principal: {
      kind: admin ? "admin" : role === "reviewer" ? "reviewer" : "user",
      id: "user-1",
      name: "Pat Person",
      actor: "user:user-1",
      scopes: spec.scopes,
      is_reviewer: admin || role === "reviewer",
      is_platform_admin: admin,
      manages_team: admin || role === "org_admin",
      restricted_to_organizations: kind === "organization" ? ["org-1"] : [],
      restricted_to_industries: [],
    },
    user: { id: "user-1", account_id: "acct-1", email: "pat@example.com", name: "Pat Person", role, role_label: spec.label, scopes: spec.scopes, industries: [], status: "active", created_at: "2026-11-01T00:00:00Z", last_login_at: null, invited_by: null },
    account: { id: "acct-1", kind, name: kind === "platform" ? "Humaital" : "Acme Corp", org_id: kind === "organization" ? "org-1" : null, email_domain: "example.com", created_at: "2026-11-01T00:00:00Z" },
    session_id: "sess-1",
    roles: ROLES,
  };
}

const SESSION_TOKEN = "h." + btoa(JSON.stringify({ sub: "user-1", name: "Pat Person", role: "admin", sid: "sess-1", exp: 9999999999 })) + ".s";
const EMPTY_PAGE = { items: [], total: 0, limit: 50, offset: 0 };

function renderApp(route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function workspaceRoutes(me: Me) {
  return (url: string, init?: RequestInit) => {
    if (url === "/v1/auth/status") return { body: { bootstrapped: true, signup: "invitation", platform_name: "Humaital" } };
    if (url === "/v1/auth/me") return { body: me };
    if (url === "/health") return { body: { status: "ok", ontology_version: "1.0.0", methodology_version: "1.0.0" } };
    if (url.startsWith("/v1/assessments?") || url.startsWith("/v1/reviews/tasks?")) return { body: EMPTY_PAGE };
    if (url === "/v1/auth/logout" && init?.method === "POST") return { status: 204 };
    return undefined;
  };
}

describe("Auth gate", () => {
  it("sends a visitor without credentials to the sign-in page and keeps verification public", async () => {
    mockFetch(workspaceRoutes(meFor("owner", "platform")));
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Verify a certificate/ })).toHaveAttribute("href", "/verify");
    renderApp("/verify");
    expect(await screen.findByLabelText("Certificate number")).toBeInTheDocument();
  });

  it("sends a signed-in user from the sign-in page to the workspace", async () => {
    localStorage.setItem("hai.session", SESSION_TOKEN);
    mockFetch(workspaceRoutes(meFor("owner", "platform")));
    renderApp("/login");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});

describe("Login", () => {
  it("signs in with email and password, stores the session and opens the dashboard", async () => {
    const user = userEvent.setup();
    const me = meFor("owner", "platform");
    const { calls } = mockFetch((url, init) => {
      if (url === "/v1/auth/login" && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { email: string; password: string; remember_me: boolean };
        if (body.password !== "correct horse battery") return { status: 401, body: { error: { code: "unauthorized", message: "invalid email or password", details: {} } } };
        return { body: { token: SESSION_TOKEN, token_type: "bearer", expires_at: "2027-01-01T00:00:00Z", me } };
      }
      return workspaceRoutes(me)(url, init);
    });
    renderApp("/login");
    await user.type(await screen.findByLabelText("Email"), "pat@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid email or password");
    expect(localStorage.getItem("hai.session")).toBeNull();
    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("checkbox", { name: /Keep me signed in/ }));
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(localStorage.getItem("hai.session")).toBe(SESSION_TOKEN);
    const login = calls.filter((c) => c.url === "/v1/auth/login").at(-1);
    expect(JSON.parse(String(login?.init?.body))).toEqual({ email: "pat@example.com", password: "correct horse battery", remember_me: true });
    // the session is sent as a bearer token afterwards
    const meCall = calls.find((c) => c.url === "/v1/auth/me");
    expect((meCall?.init?.headers as Record<string, string>)["Authorization"]).toBe(`Bearer ${SESSION_TOKEN}`);
  });

  it("still lets a partner continue with an API key", async () => {
    const user = userEvent.setup();
    mockFetch((url, init) => {
      if (url === "/v1/auth/me") return { body: { ...meFor("viewer", "platform"), user: null, account: null, session_id: null, principal: { ...meFor("viewer", "platform").principal, kind: "api_key", name: "partner" } } };
      return workspaceRoutes(meFor("viewer", "platform"))(url, init);
    });
    renderApp("/login");
    await user.click(await screen.findByText("Use an API key or reviewer token instead"));
    await user.type(screen.getByLabelText("API key"), "hai_example.fake-secret");
    await user.click(screen.getByRole("button", { name: "Continue with credentials" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(localStorage.getItem("hai.apiKey")).toBe("hai_example.fake-secret");
    expect(localStorage.getItem("hai.session")).toBeNull();
  });

  it("shows a dropped session as a sign-in page, not a broken dashboard", async () => {
    localStorage.setItem("hai.session", SESSION_TOKEN);
    mockFetch((url) => {
      if (url === "/v1/auth/me" || url.startsWith("/v1/assessments")) return { status: 401, body: { error: { code: "unauthorized", message: "session expired or signed out; sign in again", details: {} } } };
      return workspaceRoutes(meFor("owner", "platform"))(url);
    });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(localStorage.getItem("hai.session")).toBeNull();
  });
});

describe("Signup", () => {
  it("accepts an invitation: shows who is invited, requires a name and matching passwords, then signs in", async () => {
    const user = userEvent.setup();
    const me = meFor("org_member", "organization");
    const { calls } = mockFetch((url, init) => {
      if (url === "/v1/auth/invitations/hai_inv_abc") {
        return { body: { id: "inv-1", kind: "invite", account_id: "acct-1", user_id: null, email: "cfo@acme.example", role: "org_member", role_label: "Organization member", scopes: [], industries: [], invited_by: "user:owner", invited_by_name: "Olu Owner", message: "Welcome aboard.", status: "pending", expires_at: "2027-01-01T00:00:00Z", accepted_at: null, revoked_at: null, created_at: "2026-11-01T00:00:00Z", account: me.account } };
      }
      if (url === "/v1/auth/register" && init?.method === "POST") return { status: 201, body: { token: SESSION_TOKEN, token_type: "bearer", expires_at: "2027-01-01T00:00:00Z", me } };
      return workspaceRoutes(me)(url, init);
    });
    renderApp("/signup?token=hai_inv_abc");
    expect(await screen.findByRole("heading", { name: "Join Acme Corp" })).toBeInTheDocument();
    expect(screen.getByText("cfo@acme.example")).toBeInTheDocument();
    expect(screen.getByText("Organization member")).toBeInTheDocument();
    expect(screen.getByText("Welcome aboard.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText("Enter your name.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your name"), "Chi Finance");
    await user.type(screen.getByLabelText("Password"), "a-long-enough-passphrase");
    await user.type(screen.getByLabelText("Confirm password"), "a-different-passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The passwords do not match.");
    expect(calls.some((c) => c.url === "/v1/auth/register")).toBe(false);
    await user.clear(screen.getByLabelText("Confirm password"));
    await user.type(screen.getByLabelText("Confirm password"), "a-long-enough-passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("heading", { name: "Your reports" })).toBeInTheDocument();
    expect(localStorage.getItem("hai.session")).toBe(SESSION_TOKEN);
    const register = calls.find((c) => c.url === "/v1/auth/register");
    expect(JSON.parse(String(register?.init?.body))).toEqual({ token: "hai_inv_abc", name: "Chi Finance", password: "a-long-enough-passphrase" });
  });

  it("explains a spent invitation and offers the way forward", async () => {
    mockFetch((url) => url.startsWith("/v1/auth/invitations/") ? { status: 409, body: { error: { code: "conflict", message: "this invitation is accepted", details: { status: "accepted" } } } } : undefined);
    renderApp("/signup?token=hai_inv_used");
    expect(await screen.findByRole("heading", { name: "This link is accepted" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go to sign in/ })).toHaveAttribute("href", "/login");
  });

  it("offers first-run setup when the platform has no owner, and access requests afterwards", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch((url, init) => {
      if (url === "/v1/auth/status") return { body: { bootstrapped: false, signup: "invitation", platform_name: "Humaital" } };
      if (url === "/v1/auth/access-requests" && init?.method === "POST") return { status: 201, body: { id: "r1", status: "pending", created_at: "2026-11-01T00:00:00Z" } };
      return undefined;
    });
    renderApp("/signup");
    expect(await screen.findByRole("heading", { name: "Set up the platform" })).toBeInTheDocument();
    expect(screen.getByLabelText("Platform name")).toHaveValue("Humaital");

    mockFetch((url, init) => {
      if (url === "/v1/auth/status") return { body: { bootstrapped: true, signup: "invitation", platform_name: "Humaital" } };
      if (url === "/v1/auth/access-requests" && init?.method === "POST") { calls.push({ url, init }); return { status: 201, body: { id: "r1", status: "pending", created_at: "2026-11-01T00:00:00Z" } }; }
      return undefined;
    });
    renderApp("/signup");
    const form = (await screen.findByRole("heading", { name: "Request access" })).closest("form") as HTMLElement;
    await user.type(within(form).getByLabelText("Your name"), "Nia");
    await user.type(within(form).getByLabelText("Work email"), "cto@newco.example");
    await user.type(within(form).getByLabelText("Organization"), "Newco");
    await user.click(within(form).getByRole("button", { name: "Send request" }));
    expect(await screen.findByRole("heading", { name: "Request sent" })).toBeInTheDocument();
    const sent = calls.find((c) => c.url === "/v1/auth/access-requests");
    expect(JSON.parse(String(sent?.init?.body))).toMatchObject({ email: "cto@newco.example", name: "Nia", organization_name: "Newco" });
  });
});

describe("Role-based navigation", () => {
  it("shows an organization member only what their role allows", async () => {
    localStorage.setItem("hai.session", SESSION_TOKEN);
    mockFetch(workspaceRoutes(meFor("org_member", "organization")));
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Your reports" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: /Dashboard/ })).toBeInTheDocument());
    expect(within(nav).queryByRole("link", { name: /New assessment/ })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: /Review queue/ })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: /Team and access/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /New assessment/ })).not.toBeInTheDocument();
    expect(screen.getAllByText("Acme Corp").length).toBeGreaterThan(0);
  });

  it("shows the platform owner the review queue and team administration", async () => {
    localStorage.setItem("hai.session", SESSION_TOKEN);
    mockFetch(workspaceRoutes(meFor("owner", "platform")));
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(await within(nav).findByRole("link", { name: /Team and access/ })).toHaveAttribute("href", "/team");
    expect(within(nav).getByRole("link", { name: /Review queue/ })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /New assessment/ })).toBeInTheDocument();
  });

  it("signs out from the account menu and returns to the sign-in page", async () => {
    const user = userEvent.setup();
    localStorage.setItem("hai.session", SESSION_TOKEN);
    const { calls } = mockFetch(workspaceRoutes(meFor("owner", "platform")));
    renderApp("/");
    await screen.findByRole("heading", { name: "Dashboard" });
    await user.click(screen.getByRole("button", { name: "Account menu" }));
    await user.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(localStorage.getItem("hai.session")).toBeNull();
    expect(calls.some((c) => c.url === "/v1/auth/logout" && c.init?.method === "POST")).toBe(true);
  });
});

describe("Team", () => {
  it("lets the owner invite an organization user and shows the link once", async () => {
    const user = userEvent.setup();
    localStorage.setItem("hai.session", SESSION_TOKEN);
    const me = meFor("owner", "platform");
    const { calls } = mockFetch((url, init) => {
      if (url === "/v1/team/roles") return { body: ROLES };
      if (url === "/v1/team/users") return { body: { items: [{ ...me.user, account: me.account }], total: 1, limit: 1, offset: 0 } };
      if (url === "/v1/team/invitations" && (!init?.method || init.method === "GET")) return { body: EMPTY_PAGE };
      if (url.startsWith("/v1/team/access-requests")) return { body: EMPTY_PAGE };
      if (url === "/v1/team/accounts") return { body: EMPTY_PAGE };
      if (url.startsWith("/v1/organizations")) return { body: { items: [{ id: "org-1", legal_name: "Acme Corp", display_name: "Acme Corp", primary_domain: "acme.example", aliases: [], industry_code: "Software", stage_band: null, size_band: null, identifiers: {}, identifiers_verified: false, entity_confidence: null, created_at: null }], total: 1, limit: 50, offset: 0 } };
      if (url === "/v1/team/invitations" && init?.method === "POST") {
        return { status: 201, body: { id: "inv-1", kind: "invite", account_id: "acct-2", user_id: null, email: "cfo@acme.example", role: "org_member", role_label: "Organization member", scopes: [], industries: [], invited_by: "user:user-1", invited_by_name: "Pat Person", message: null, status: "pending", expires_at: "2027-01-01T00:00:00Z", accepted_at: null, revoked_at: null, created_at: "2026-11-01T00:00:00Z", token: "hai_inv_new", invite_path: "/signup?token=hai_inv_new", invite_url: "http://console.example/signup?token=hai_inv_new", account: { id: "acct-2", kind: "organization", name: "Acme Corp", org_id: "org-1", email_domain: "acme.example", created_at: "2026-11-01T00:00:00Z" }, domain_match: true } };
      }
      return workspaceRoutes(me)(url, init);
    });
    renderApp("/team");
    expect(await screen.findByRole("heading", { name: "Team and access" })).toBeInTheDocument();
    expect(await screen.findByText("pat@example.com")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Invite a user/ }));
    await user.type(screen.getByLabelText("Email"), "cfo@acme.example");
    await user.selectOptions(screen.getByLabelText("Role"), "org_member");
    await user.selectOptions(await screen.findByLabelText("Organization"), "org-1");
    await user.click(screen.getByRole("button", { name: /Create invitation/ }));
    expect(await screen.findByRole("heading", { name: /Invitation ready for cfo@acme.example/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Invitation link")).toHaveValue(`${window.location.origin}/signup?token=hai_inv_new`);
    const post = calls.find((c) => c.url === "/v1/team/invitations" && c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ email: "cfo@acme.example", role: "org_member", org_id: "org-1" });
  });
});
