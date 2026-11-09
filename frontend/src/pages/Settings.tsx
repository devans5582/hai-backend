import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Badge, QueryState, Tabs } from "../components/widgets";
import { api, ApiRequestError, type ApiKey, type Me } from "../lib/api";
import { clearAllCredentials, useAuth, type Credentials } from "../lib/auth";
import { fmtDateTime } from "../lib/format";
import { useMe } from "../lib/me";
import { roleLabel } from "../lib/roles";

type Tab = "profile" | "security" | "access";

export function Settings() {
  const auth = useAuth();
  const { me, isLoading } = useMe();
  const [params, setParams] = useSearchParams();
  const defaultTab: Tab = auth.mode === "session" ? "profile" : "access";
  const tab = (params.get("tab") as Tab | null) ?? defaultTab;
  const setTab = (next: Tab) => setParams(next === defaultTab ? {} : { tab: next });
  const session = auth.mode === "session";
  const tabs: { id: Tab; label: string }[] = session
    ? [{ id: "profile", label: "Profile" }, { id: "security", label: "Security" }, { id: "access", label: "API access" }]
    : [{ id: "access", label: "API access" }, { id: "profile", label: "Profile" }];
  return (
    <div className="stack settings-page">
      <div className="page-head">
        <div>
          <p className="eyebrow">{me?.account?.name ?? "Your workspace"}</p>
          <h1>Settings</h1>
          <p className="page-description">{session ? "Your profile, sign-in security and the API keys that let other systems use your access." : "Manage the credentials this browser uses and the API keys available to you."}</p>
        </div>
      </div>
      <Tabs<Tab> tabs={tabs} value={tab} onChange={setTab} />
      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "profile" && <Profile me={me} loading={isLoading} session={session} />}
        {tab === "security" && session && <Security />}
        {tab === "access" && <Access me={me} session={session} />}
      </div>
    </div>
  );
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) {
    const fields = Object.values(err.fieldErrors);
    return fields.length ? fields.join(" ") : err.message;
  }
  return "The request failed. Try again in a moment.";
}

function Profile({ me, loading, session }: { me: Me | undefined; loading: boolean; session: boolean }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (next: string) => api.updateMe({ name: next }),
    onSuccess: () => { setMessage("Profile saved."); setName(null); void queryClient.invalidateQueries({ queryKey: ["me"] }); },
    onError: (err) => setMessage(errorMessage(err)),
  });
  const current = name ?? me?.user?.name ?? "";
  if (loading) return <QueryState isLoading error={null}>{null}</QueryState>;
  if (!me) return <div className="alert info">Sign in to see your profile. Certificate verification works without an account.</div>;
  const restrictedOrgs = me.principal.restricted_to_organizations;
  const restrictedIndustries = me.principal.restricted_to_industries;
  return (
    <div className="settings-grid">
      <form className="card" onSubmit={(e) => { e.preventDefault(); if (current.trim()) save.mutate(current.trim()); }}>
        <div className="section-heading"><Icon name="user" /><div><h2>Profile</h2><p className="muted small">{session ? "How your name appears on reviews and decisions." : "This access has no console profile."}</p></div></div>
        <div className="form-section">
          {me.user ? (
            <>
              <div className="field">
                <label htmlFor="profile-name">Name</label>
                <input id="profile-name" value={current} onChange={(e) => { setName(e.target.value); setMessage(null); }} autoComplete="name" />
              </div>
              <div className="field">
                <label htmlFor="profile-email">Email</label>
                <input id="profile-email" value={me.user.email} readOnly aria-describedby="email-help" />
                <div id="email-help" className="help">Your sign-in email. Ask an administrator if it needs to change.</div>
              </div>
            </>
          ) : (
            <dl className="certificate-facts profile-facts">
              <div><dt>Principal</dt><dd className="mono">{me.principal.actor}</dd></div>
              <div><dt>Name</dt><dd>{me.principal.name}</dd></div>
              <div><dt>Kind</dt><dd>{me.principal.kind === "api_key" ? "API key" : me.principal.is_reviewer ? "Minted reviewer token" : me.principal.kind}</dd></div>
            </dl>
          )}
        </div>
        {me.user && (
          <div className="form-footer">
            <div className="actions"><button type="submit" className="primary" disabled={save.isPending || !current.trim() || current.trim() === me.user.name}><Icon name="check" /> Save profile</button></div>
            {message && <p role="status" className="small success-message"><Icon name="check-circle" /> {message}</p>}
          </div>
        )}
      </form>
      <aside className="stack">
        <div className="card access-card">
          <div className="section-heading"><Icon name="shield" /><h2>Your access</h2></div>
          <Badge tone="red">{me.user ? roleLabel(me.user.role, me.roles.roles) : me.principal.kind === "api_key" ? "API key" : "Reviewer token"}</Badge>
          {me.account && <><h3>{me.account.name}</h3><p className="muted small">{me.account.kind === "organization" ? "Participating organization account" : "Humaital platform account"}</p></>}
          {restrictedOrgs.length > 0 && <p className="small muted">You see the reports of your organization only.</p>}
          {restrictedIndustries.length > 0 && <p className="small muted">Industries: {restrictedIndustries.join(", ")}</p>}
          <h3 className="small">Permissions</h3>
          <ul className="permission-list">
            {me.roles.scopes.filter((s) => me.principal.scopes.includes(s.code) || (me.principal.is_platform_admin && s.code !== "admin")).map((s) => <li key={s.code}><Icon name="check" />{s.label}</li>)}
          </ul>
        </div>
        {me.user?.invited_by && <div className="card"><h3>Invited by</h3><p className="muted small mono">{me.user.invited_by}</p></div>}
      </aside>
    </div>
  );
}

function Security() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const sessions = useQuery({ queryKey: ["my-sessions"], queryFn: api.mySessions });
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const change = useMutation({
    mutationFn: () => api.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => { setMessage("Password changed. Other sessions were signed out."); setError(null); setCurrent(""); setNext(""); setConfirm(""); void sessions.refetch(); },
    onError: (err) => { setError(errorMessage(err)); setMessage(null); },
  });
  const signOutEverywhere = useMutation({
    mutationFn: () => api.logout(true),
    onSuccess: () => { clearAllCredentials(); queryClient.clear(); navigate("/login", { replace: true }); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!current || !next) { setError("Enter your current password and a new one."); return; }
    if (next.length < 10) { setError("Use at least 10 characters for the new password."); return; }
    if (next !== confirm) { setError("The new passwords do not match."); return; }
    change.mutate();
  };
  return (
    <div className="settings-grid">
      <form className="card" onSubmit={submit} noValidate>
        <div className="section-heading"><Icon name="lock" /><div><h2>Change password</h2><p className="muted small">Changing it signs out every other device.</p></div></div>
        <div className="form-section">
          {error && <div className="alert error" role="alert">{error}</div>}
          <div className="field"><label htmlFor="current-password">Current password</label><input id="current-password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></div>
          <div className="form-grid">
            <div className="field"><label htmlFor="next-password">New password</label><input id="next-password" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /><div className="help">At least 10 characters.</div></div>
            <div className="field"><label htmlFor="confirm-next-password">Confirm new password</label><input id="confirm-next-password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></div>
          </div>
        </div>
        <div className="form-footer">
          <div className="actions"><button type="submit" className="primary" disabled={change.isPending}><Icon name="check" /> Change password</button></div>
          {message && <p role="status" className="small success-message"><Icon name="check-circle" /> {message}</p>}
        </div>
      </form>
      <aside className="stack">
        <div className="card">
          <div className="section-heading"><Icon name="globe" /><h2>Active sessions</h2></div>
          <QueryState isLoading={sessions.isLoading} error={sessions.error}>
            <ul className="session-list">
              {(sessions.data?.items ?? []).map((s) => <li key={s.id}><strong>{s.current ? "This device" : "Another device"}</strong><span className="small muted">{s.user_agent ? s.user_agent.slice(0, 70) : "Unknown browser"}</span><span className="small muted">Last seen {fmtDateTime(s.last_seen_at ?? s.created_at)} · expires {fmtDateTime(s.expires_at)}</span></li>)}
            </ul>
          </QueryState>
          <button type="button" onClick={() => signOutEverywhere.mutate()} disabled={signOutEverywhere.isPending}><Icon name="log-out" />Sign out everywhere</button>
        </div>
        <div className="card"><h3>Forgot your password?</h3><p className="muted small">An administrator can issue a one-time reset link from the Team page.</p></div>
      </aside>
    </div>
  );
}

function Access({ me, session }: { me: Me | undefined; session: boolean }) {
  return (
    <div className="stack">
      {me && me.principal.kind !== "api_key" && <ApiKeys me={me} />}
      {me?.principal.kind === "api_key" && <div className="alert info">You are connected with an API key. Sign in to the console to create or revoke keys.</div>}
      <CredentialsForm session={session} />
    </div>
  );
}

function ApiKeys({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: api.apiKeys });
  const [name, setName] = useState("");
  const grantable = me.roles.scopes.filter((s) => s.code !== "admin" && (me.principal.is_platform_admin || me.principal.scopes.includes(s.code)));
  const [scopes, setScopes] = useState<string[] | null>(null);
  const [created, setCreated] = useState<(ApiKey & { api_key: string }) | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const effective = scopes ?? grantable.map((s) => s.code);
  const create = useMutation({
    mutationFn: () => api.createApiKey({ name: name.trim(), scopes: effective }),
    onSuccess: (key) => { setCreated(key); setName(""); setScopes(null); setError(null); void queryClient.invalidateQueries({ queryKey: ["api-keys"] }); },
    onError: (err) => setError(errorMessage(err)),
  });
  const revoke = useMutation({ mutationFn: (id: string) => api.revokeApiKey(id), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["api-keys"] }) });
  const copy = async () => { if (!created) return; try { await navigator.clipboard.writeText(created.api_key); setCopied(true); } catch { setCopied(false); } };
  const items = keys.data?.items ?? [];
  const canSee = me.principal.scopes.length > 0;
  return (
    <div className="settings-grid">
      <div className="card settings-card">
        <div className="section-heading"><Icon name="key" /><div><h2>API keys</h2><p className="muted small">{me.account?.kind === "organization" ? "Keys created here see your organization's reports only, whatever system uses them." : "Keys carry at most your own permissions and are owned by your account."}</p></div></div>
        {created && (
          <div className="invite-result form-section">
            <p className="small"><strong>Key "{created.name}" created.</strong> Copy it now; it will not be shown again.</p>
            <div className="invite-link"><label className="sr-only" htmlFor="new-key">New API key</label><input id="new-key" readOnly className="mono" value={created.api_key} onFocus={(e) => e.currentTarget.select()} /><button type="button" className="primary" onClick={() => void copy()}><Icon name="copy" />{copied ? "Copied" : "Copy key"}</button></div>
            <div className="actions"><button type="button" onClick={() => { setCreated(null); setCopied(false); }}>Done</button></div>
          </div>
        )}
        {!created && canSee && (
          <form className="form-section" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); else setError("Give the key a name."); }} noValidate>
            {error && <div className="alert error" role="alert">{error}</div>}
            <div className="field"><label htmlFor="key-name">Key name</label><input id="key-name" value={name} onChange={(e) => { setName(e.target.value); setError(null); }} placeholder="e.g. GRC integration" /></div>
            <fieldset className="field permissions"><legend>Permissions</legend>
              <div className="permission-grid">
                {grantable.map((s) => <label key={s.code} className="checkbox-card"><input type="checkbox" checked={effective.includes(s.code)} onChange={(e) => { const base = new Set(effective); if (e.target.checked) base.add(s.code); else base.delete(s.code); setScopes(Array.from(base)); }} /><span><strong>{s.label}</strong><span className="help">{s.description}</span></span></label>)}
              </div>
            </fieldset>
            <div className="actions"><button type="submit" className="primary" disabled={create.isPending}><Icon name="plus" />Create key</button></div>
          </form>
        )}
        <div className="table-wrap">
          <QueryState isLoading={keys.isLoading} error={keys.error}>
            {items.length === 0 ? <p className="table-empty small">No API keys yet.</p> : (
              <table>
                <thead><tr><th>Name</th><th>Key id</th><th>Permissions</th><th>Last used</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>
                  {items.map((k) => (
                    <tr key={k.id} className={k.status === "revoked" ? "row-disabled" : ""}>
                      <td>{k.name}<div className="small muted mono">{k.created_by}</div></td>
                      <td className="mono small">{k.key_id}</td>
                      <td className="small muted">{k.scopes.includes("admin") ? "Administration" : k.scopes.length} {k.scopes.includes("admin") ? "" : "scopes"}</td>
                      <td className="small muted">{k.last_used_at ? fmtDateTime(k.last_used_at) : "Never"}</td>
                      <td>{k.status === "active" ? <Badge tone="ok">Active</Badge> : <Badge tone="bad">Revoked</Badge>}</td>
                      <td>{k.status === "active" && <button type="button" onClick={() => { if (window.confirm(`Revoke the key "${k.name}"? Systems using it stop working immediately.`)) revoke.mutate(k.key_id); }} aria-label={`Revoke ${k.name}`}>Revoke</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </QueryState>
        </div>
      </div>
      <aside className="stack">
        <div className="card"><h3>Using a key</h3><p className="muted small">Send it as the <code>X-API-Key</code> header. Keys are hashed at rest and can be revoked here at any time; the audit log records who created and revoked each one.</p><Link className="text-link" to="/ontology">API and methodology <Icon name="arrow-right" /></Link></div>
      </aside>
    </div>
  );
}

/** The browser-stored credential path, kept for partners and operators. */
function CredentialsForm({ session }: { session: boolean }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState(auth.apiKey ?? "");
  const [token, setToken] = useState(auth.reviewerToken ?? "");
  const [showKey, setShowKey] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [message, setMessage] = useState("");
  const persist = (credentials: Partial<Credentials>, confirmation: string) => {
    auth.save(credentials);
    // Reset cached results and authorization errors before fetching with new credentials.
    void queryClient.resetQueries();
    setMessage(confirmation);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    persist({ apiKey: apiKey.trim() || null, reviewerToken: token.trim() || null }, "Credentials saved.");
  };
  const expires = !session && auth.claims?.exp ? new Date(auth.claims.exp * 1000) : null;
  const expired = expires !== null && expires.getTime() < Date.now();
  const connected = !!(auth.apiKey || auth.reviewerToken);
  const changed = apiKey.trim() !== (auth.apiKey ?? "") || token.trim() !== (auth.reviewerToken ?? "");
  return (
    <details className="card optional-details credentials-details" open={!session}>
      <summary><Icon name="plus" /><span>{session ? "Browser credentials (advanced)" : "Access credentials"}</span><span className="small muted">{session ? "Partner key or minted token stored in this browser" : "API key or reviewer token"}</span></summary>
      <div className="settings-grid credentials-grid">
        <form onSubmit={submit}>
          {session && <div className="alert info"><Icon name="info" /> You are signed in; your session is used for every request. Credentials saved here apply only after you sign out.</div>}
          <div className="form-section">
            <div className="field">
              <label htmlFor="apiKey">API key</label>
              <div className="input-action">
                <input id="apiKey" type={showKey ? "text" : "password"} value={apiKey} onChange={(e) => { setApiKey(e.target.value); setMessage(""); }} placeholder="hai_xxxxxxxxxxxx.secret" autoComplete="off" spellCheck={false} aria-describedby="apiKey-help" />
                <button type="button" className="icon-button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? "Hide API key" : "Show API key"} aria-pressed={showKey}><Icon name={showKey ? "eye-off" : "eye"} /></button>
              </div>
              <div id="apiKey-help" className="help">Start assessments and read results. Ask your administrator for a key.</div>
            </div>
            <div className="field">
              <label htmlFor="token">Reviewer token (JWT)</label>
              <div className="input-action">
                <input id="token" type={showToken ? "text" : "password"} value={token} onChange={(e) => { setToken(e.target.value); setMessage(""); }} placeholder="Paste your reviewer token" autoComplete="off" spellCheck={false} aria-describedby="token-help" />
                <button type="button" className="icon-button" onClick={() => setShowToken(!showToken)} aria-label={showToken ? "Hide reviewer token" : "Show reviewer token"} aria-pressed={showToken}><Icon name={showToken ? "eye-off" : "eye"} /></button>
              </div>
              <div id="token-help" className="help">Review evidence and sign certification decisions. When both are saved, the reviewer token is used.</div>
            </div>
            <div className="credential-note"><Icon name="lock" /><span className="small muted">Credentials are saved in this browser. Clear them when using a shared device.</span></div>
          </div>
          <div className="form-footer">
            <div className="actions">
              <button type="submit" className="primary"><Icon name="check" /> Save credentials</button>
              <button type="button" disabled={!connected && !apiKey && !token} onClick={() => { setApiKey(""); setToken(""); setShowKey(false); setShowToken(false); persist({ apiKey: null, reviewerToken: null }, "Credentials cleared."); }}>Clear credentials</button>
            </div>
            {message ? <p role="status" className="small success-message"><Icon name="check-circle" /> {message}</p> : changed ? <p className="small muted">You have unsaved changes.</p> : null}
          </div>
        </form>
        {!session && (
          <aside className="stack">
            <div className="card access-card">
              <div className="section-heading"><Icon name="shield" /><h2>Current access</h2></div>
              <Badge tone={expired ? "warn" : connected ? "ok" : "info"}>{expired ? "Token expired" : connected ? "Credentials saved" : "Not connected"}</Badge>
              {auth.claims ? (
                <>
                  <h3>{auth.claims.name ?? auth.claims.sub}</h3>
                  <p className="muted small">{auth.claims.role === "admin" ? "Administrator" : auth.claims.role === "reviewer" ? "Reviewer" : "Token access"}</p>
                  {expires && <p className="small muted">{expired ? "Expired" : "Expires"} {expires.toLocaleString()}</p>}
                  {(auth.claims.scopes ?? []).length > 0 && <p className="small muted">Scopes: {auth.claims.scopes?.join(", ")}</p>}
                  {expired && <p className="small">Ask your administrator for a new reviewer token to continue.</p>}
                </>
              ) : auth.reviewerToken ? (
                <p className="small muted">The saved token could not be read. Check that you copied the complete reviewer token.</p>
              ) : auth.apiKey ? (
                <><h3>API key access</h3><p className="muted small">Your key is saved. You can start assessments and read results.</p></>
              ) : (
                <p className="small muted">Add credentials to start an assessment. Certificate verification is available to everyone.</p>
              )}
            </div>
            <div className="card">
              <h3>Prefer a personal account?</h3>
              <p className="muted small">Console accounts give you a profile, named reviews and account-owned keys. <Link to="/login">Sign in</Link> or ask an administrator for an invitation.</p>
            </div>
          </aside>
        )}
      </div>
    </details>
  );
}
