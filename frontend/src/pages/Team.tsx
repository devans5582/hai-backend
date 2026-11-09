import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Badge, QueryState, Tabs } from "../components/widgets";
import { api, ApiRequestError, type AccessRequest, type InvitationWithLink, type RoleCatalog, type TeamUser } from "../lib/api";
import { INDUSTRY_VALUES, LABELS } from "../generated/ontology";
import { fmtDateTime, label } from "../lib/format";
import { useMe } from "../lib/me";

type Tab = "members" | "invitations" | "requests" | "accounts";

export function Team() {
  const { me, capabilities } = useMe();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "members";
  const setTab = (next: Tab) => setParams(next === "members" ? {} : { tab: next });
  const roles = useQuery({ queryKey: ["team-roles"], queryFn: api.teamRoles });
  const users = useQuery({ queryKey: ["team-users"], queryFn: api.teamUsers });
  const invitations = useQuery({ queryKey: ["team-invitations"], queryFn: api.teamInvitations });
  const requests = useQuery({ queryKey: ["access-requests"], queryFn: () => api.accessRequests("pending"), enabled: capabilities.platformAdmin });
  const accounts = useQuery({ queryKey: ["team-accounts"], queryFn: api.teamAccounts, enabled: capabilities.platformAdmin });
  const [prefill, setPrefill] = useState<Partial<{ email: string; name: string }> | null>(null);
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "members", label: `Members${users.data ? ` (${users.data.total})` : ""}` },
    { id: "invitations", label: `Invitations${invitations.data ? ` (${invitations.data.total})` : ""}` },
    ...(capabilities.platformAdmin ? [{ id: "requests" as const, label: `Access requests${requests.data ? ` (${requests.data.total})` : ""}` }, { id: "accounts" as const, label: "Organizations" }] : []),
  ];
  const organizationAccount = me?.account?.kind === "organization";
  return (
    <div className="stack team-page">
      <div className="page-head">
        <div>
          <span className="eyebrow">{organizationAccount ? me?.account?.name : "Administration"}</span>
          <h1>Team and access</h1>
          <p className="page-description">{organizationAccount ? "Invite colleagues to see your organization's reports. Everyone you invite sees the same organization and nothing else." : "Invite reviewers, analysts and participating organizations. Each role carries a fixed set of permissions you can narrow, and platform users can be limited to the industries they serve."}</p>
        </div>
      </div>
      <InviteForm key={prefill?.email ?? "blank"} catalog={roles.data} platformAdmin={capabilities.platformAdmin} initialEmail={prefill?.email ?? ""} initialOpen={!!prefill} onDone={() => { setPrefill(null); void invitations.refetch(); void requests.refetch(); setTab("invitations"); }} />
      <Tabs<Tab> tabs={tabs} value={tab} onChange={setTab} />
      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "members" && <Members query={users} catalog={roles.data} selfId={me?.user?.id ?? null} isOwner={me?.user?.role === "owner"} platformAdmin={capabilities.platformAdmin} />}
        {tab === "invitations" && <Invitations query={invitations} />}
        {tab === "requests" && capabilities.platformAdmin && <Requests query={requests} onInvite={(r) => { setPrefill({ email: r.email, name: r.name }); window.scrollTo({ top: 0, behavior: "smooth" }); }} />}
        {tab === "accounts" && capabilities.platformAdmin && <Accounts query={accounts} />}
      </div>
    </div>
  );
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) {
    const fields = Object.values(err.fieldErrors);
    return fields.length ? `${err.message}: ${fields.join("; ")}` : err.message;
  }
  return "The request failed. Try again in a moment.";
}

function InviteForm({ catalog, platformAdmin, initialEmail, initialOpen, onDone }: { catalog: RoleCatalog | undefined; platformAdmin: boolean; initialEmail: string; initialOpen: boolean; onDone: () => void }) {
  const [open, setOpen] = useState(initialOpen);
  const [email, setEmail] = useState(initialEmail);
  const [role, setRole] = useState("");
  const [orgId, setOrgId] = useState("");
  const [orgQuery, setOrgQuery] = useState("");
  const [industries, setIndustries] = useState<string[]>([]);
  const [scopes, setScopes] = useState<string[] | null>(null);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<InvitationWithLink | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const orgs = useQuery({ queryKey: ["organizations", orgQuery, "invite"], queryFn: () => api.listOrganizations(orgQuery || undefined), enabled: platformAdmin });
  const roleSpec = catalog?.roles.find((r) => r.code === role);
  const isOrgRole = roleSpec?.account_kind === "organization";
  const effectiveScopes = scopes ?? roleSpec?.scopes ?? [];
  const invite = useMutation({
    mutationFn: () => api.invite({
      email: email.trim(),
      role,
      org_id: isOrgRole && platformAdmin ? orgId || undefined : undefined,
      industries: !isOrgRole && industries.length ? industries : undefined,
      scopes: scopes && roleSpec?.narrowable ? scopes : undefined,
      message: message.trim() || undefined,
    }),
    onSuccess: (data) => { setResult(data); setError(null); onDone(); },
    onError: (err) => setError(errorMessage(err)),
  });
  const groups = useMemo(() => {
    const list = catalog?.roles ?? [];
    return [
      { title: "Humaital platform", roles: list.filter((r) => r.account_kind === "platform") },
      { title: "Participating organization", roles: list.filter((r) => r.account_kind === "organization") },
    ].filter((g) => g.roles.length);
  }, [catalog]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.trim()) { setError("Enter the invitee's email."); return; }
    if (!role) { setError("Choose a role."); return; }
    if (isOrgRole && platformAdmin && !orgId) { setError("Choose the organization this person belongs to."); return; }
    invite.mutate();
  };
  const reset = () => { setEmail(""); setRole(""); setOrgId(""); setIndustries([]); setScopes(null); setMessage(""); setResult(null); setCopied(false); setError(null); };
  const link = result ? `${window.location.origin}${result.invite_path}` : "";
  const copy = async () => {
    try { await navigator.clipboard.writeText(link); setCopied(true); } catch { setCopied(false); }
  };
  if (result) {
    return (
      <section className="card invite-result" aria-labelledby="invite-result-title">
        <div className="section-heading"><Icon name="check-circle" /><div><h2 id="invite-result-title">Invitation ready for {result.email}</h2><p className="muted small">{result.role_label} in {result.account.name}. Shown once: copy the link and send it to them yourself. It expires {fmtDateTime(result.expires_at)}.</p></div></div>
        {result.domain_match === false && <div className="alert info"><Icon name="alert-triangle" /> The email domain does not match the organization's domain. Double-check this is the right person before sending.</div>}
        <div className="invite-link">
          <label htmlFor="invite-link" className="sr-only">Invitation link</label>
          <input id="invite-link" readOnly value={link} onFocus={(e) => e.currentTarget.select()} className="mono" />
          <button type="button" className="primary" onClick={() => void copy()}><Icon name="copy" />{copied ? "Copied" : "Copy link"}</button>
        </div>
        <div className="actions"><button type="button" onClick={reset}><Icon name="user-plus" />Invite someone else</button><button type="button" className="ghost" onClick={() => { reset(); setOpen(false); }}>Done</button></div>
      </section>
    );
  }
  if (!open) {
    return <div className="actions"><button type="button" className="primary" onClick={() => setOpen(true)}><Icon name="user-plus" />Invite a user</button></div>;
  }
  return (
    <form className="card invite-form" onSubmit={submit} noValidate aria-labelledby="invite-title">
      <div className="section-heading"><Icon name="user-plus" /><div><h2 id="invite-title">Invite a user</h2><p className="muted small">They receive a one-time link to create their account. No email is sent by the platform; you share the link.</p></div></div>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="form-grid">
        <div className="field">
          <label htmlFor="invite-email">Email</label>
          <input id="invite-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="person@organization.com" />
          <div className="help">Participating organizations should use their organization email.</div>
        </div>
        <div className="field">
          <label htmlFor="invite-role">Role</label>
          <select id="invite-role" value={role} onChange={(e) => { setRole(e.target.value); setScopes(null); }}>
            <option value="">Choose a role</option>
            {groups.map((g) => <optgroup key={g.title} label={g.title}>{g.roles.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}</optgroup>)}
          </select>
          {roleSpec && <div className="help">{roleSpec.description}</div>}
        </div>
      </div>
      {isOrgRole && platformAdmin && (
        <div className="field">
          <label htmlFor="invite-org">Organization</label>
          <div className="org-picker">
            <div className="search-input"><Icon name="search" /><label className="sr-only" htmlFor="invite-org-search">Search organizations</label><input id="invite-org-search" type="search" value={orgQuery} onChange={(e) => setOrgQuery(e.target.value)} placeholder="Filter by name or domain" /></div>
            <select id="invite-org" value={orgId} onChange={(e) => setOrgId(e.target.value)} size={Math.min(6, Math.max(2, orgs.data?.items.length ?? 2))}>
              {(orgs.data?.items ?? []).map((o) => <option key={o.id} value={o.id}>{o.display_name} ({o.primary_domain}){o.industry_code ? ` · ${label("industry", o.industry_code)}` : ""}</option>)}
            </select>
          </div>
          <div className="help">{orgs.data && orgs.data.total === 0 ? "No organizations yet: an organization appears here once it has been assessed." : "Only assessed organizations can be invited. Their users see that organization's reports and nothing else."}</div>
        </div>
      )}
      {roleSpec && !isOrgRole && (
        <fieldset className="field permissions">
          <legend>Industries they serve <span className="muted">(optional)</span></legend>
          <div className="permission-grid industry-grid">
            {INDUSTRY_VALUES.map((code) => (
              <label key={code} className="checkbox-card"><input type="checkbox" checked={industries.includes(code)} onChange={(e) => setIndustries(e.target.checked ? [...industries, code] : industries.filter((x) => x !== code))} /><span><strong>{LABELS["industry"]?.[code] ?? code}</strong></span></label>
            ))}
          </div>
          <div className="help">Leave every box empty for all industries. With industries ticked, this person sees only organizations in those industries.</div>
        </fieldset>
      )}
      {roleSpec && roleSpec.narrowable && catalog && (
        <fieldset className="field permissions">
          <legend>Permissions <span className="muted">(what they can see and do)</span></legend>
          <div className="permission-grid">
            {catalog.scopes.filter((s) => roleSpec.scopes.includes(s.code)).map((s) => {
              const locked = s.code === "ontology:read";
              const checked = effectiveScopes.includes(s.code);
              return <label key={s.code} className="checkbox-card"><input type="checkbox" checked={checked || locked} disabled={locked} onChange={(e) => { const base = new Set(effectiveScopes); if (e.target.checked) base.add(s.code); else base.delete(s.code); setScopes(Array.from(base)); }} /><span><strong>{s.label}</strong><span className="help">{s.description}</span></span></label>;
            })}
          </div>
          <div className="help">Start from the role's defaults and untick what this person should not have. Nothing beyond the role can be granted.</div>
        </fieldset>
      )}
      <div className="field">
        <label htmlFor="invite-message">Message <span className="muted">(optional, shown on the sign-up page)</span></label>
        <textarea id="invite-message" rows={2} value={message} onChange={(e) => setMessage(e.target.value)} />
      </div>
      <div className="actions"><button type="submit" className="primary" disabled={invite.isPending}><Icon name="mail" />{invite.isPending ? "Creating…" : "Create invitation"}</button><button type="button" onClick={() => { reset(); setOpen(false); }}>Cancel</button></div>
    </form>
  );
}

function Members({ query, catalog, selfId, isOwner, platformAdmin }: { query: ReturnType<typeof useQuery<{ items: TeamUser[]; total: number }>>; catalog: RoleCatalog | undefined; selfId: string | null; isOwner: boolean; platformAdmin: boolean }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const [resetLink, setResetLink] = useState<{ email: string; link: string } | null>(null);
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof api.updateUser>[1] }) => api.updateUser(id, body),
    onSuccess: (user) => { setNotice(`${user.name} updated.`); void queryClient.invalidateQueries({ queryKey: ["team-users"] }); },
    onError: (err) => setNotice(errorMessage(err)),
  });
  const reset = useMutation({
    mutationFn: (id: string) => api.resetLink(id),
    onSuccess: (inv) => setResetLink({ email: inv.email, link: `${window.location.origin}${inv.invite_path}` }),
    onError: (err) => setNotice(errorMessage(err)),
  });
  const items = query.data?.items ?? [];
  return (
    <div className="stack">
      {notice && <p role="status" className="small success-message"><Icon name="info" /> {notice}</p>}
      {resetLink && (
        <div className="card invite-result">
          <div className="section-heading"><Icon name="key" /><div><h2>Password reset link for {resetLink.email}</h2><p className="muted small">Shown once and valid for 24 hours. Send it to them yourself.</p></div></div>
          <div className="invite-link"><label className="sr-only" htmlFor="reset-link">Reset link</label><input id="reset-link" readOnly className="mono" value={resetLink.link} onFocus={(e) => e.currentTarget.select()} /><button type="button" className="primary" onClick={() => void navigator.clipboard?.writeText(resetLink.link)}><Icon name="copy" />Copy link</button></div>
          <div className="actions"><button type="button" onClick={() => setResetLink(null)}>Done</button></div>
        </div>
      )}
      <div className="card table-wrap">
        <QueryState isLoading={query.isLoading} error={query.error}>
          {items.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name="users" /></span><h2>No members yet</h2><p>Invite the first user with the button above.</p></div> : (
            <table>
              <thead><tr><th>Member</th><th>Role</th>{platformAdmin && <th>Account</th>}<th>Industries</th><th>Status</th><th>Last sign-in</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {items.map((u) => {
                  const self = u.id === selfId;
                  const protectedOwner = u.role === "owner" && !isOwner;
                  const roleOptions = (catalog?.roles ?? []).filter((r) => r.account_kind === u.account.kind && (r.code !== "owner" || isOwner));
                  return (
                    <tr key={u.id} className={u.status === "disabled" ? "row-disabled" : ""}>
                      <td><div className="assessment-name"><span className="domain-avatar">{(u.name[0] ?? "?").toUpperCase()}</span><span>{u.name}{self && <Badge tone="info">you</Badge>}<small>{u.email}</small></span></div></td>
                      <td>
                        {self || protectedOwner ? <Badge tone="red">{u.role_label}</Badge> : (
                          <><label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.name}</label><select id={`role-${u.id}`} value={u.role} onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value } })} style={{ width: "auto", minHeight: 36 }}>{roleOptions.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}</select></>
                        )}
                      </td>
                      {platformAdmin && <td className="small">{u.account.kind === "platform" ? <span className="muted">{u.account.name}</span> : <Link to={u.account.org_id ? `/organizations/${u.account.org_id}` : "#"}>{u.account.name}</Link>}</td>}
                      <td className="small muted">{u.industries.length ? u.industries.map((i) => label("industry", i)).join(", ") : u.account.kind === "platform" ? "All" : ""}</td>
                      <td>{u.status === "active" ? <Badge tone="ok">Active</Badge> : <Badge tone="bad">Disabled</Badge>}</td>
                      <td className="small muted">{u.last_login_at ? fmtDateTime(u.last_login_at) : "Never"}</td>
                      <td>
                        {!self && !protectedOwner && (
                          <div className="actions row-actions">
                            <button type="button" onClick={() => reset.mutate(u.id)} aria-label={`Reset password for ${u.name}`}><Icon name="key" />Reset</button>
                            {u.status === "active"
                              ? <button type="button" onClick={() => { if (window.confirm(`Disable ${u.name}? They are signed out immediately.`)) update.mutate({ id: u.id, body: { status: "disabled" } }); }} aria-label={`Disable ${u.name}`}>Disable</button>
                              : <button type="button" onClick={() => update.mutate({ id: u.id, body: { status: "active" } })} aria-label={`Enable ${u.name}`}>Enable</button>}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </QueryState>
      </div>
    </div>
  );
}

function Invitations({ query }: { query: ReturnType<typeof useQuery<{ items: (InvitationWithLink | (Omit<InvitationWithLink, "token" | "invite_path" | "invite_url">))[]; total: number }>> }) {
  const queryClient = useQueryClient();
  const revoke = useMutation({ mutationFn: (id: string) => api.revokeInvitation(id), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["team-invitations"] }) });
  const items = query.data?.items ?? [];
  return (
    <div className="card table-wrap">
      <QueryState isLoading={query.isLoading} error={query.error}>
        {items.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name="mail" /></span><h2>No pending invitations</h2><p>Invitations appear here until they are accepted, revoked or expire. Links are shown only when created.</p></div> : (
          <table>
            <thead><tr><th>Invitee</th><th>Role</th><th>Account</th><th>Invited by</th><th>Expires</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id}>
                  <td><span>{i.email}</span>{i.industries.length > 0 && <div className="small muted">{i.industries.map((x) => label("industry", x)).join(", ")}</div>}</td>
                  <td><Badge tone="red">{i.role_label}</Badge></td>
                  <td className="small">{i.account.name}</td>
                  <td className="small muted">{i.invited_by_name ?? i.invited_by}</td>
                  <td className="small muted">{fmtDateTime(i.expires_at)}</td>
                  <td><button type="button" onClick={() => revoke.mutate(i.id)} aria-label={`Revoke invitation for ${i.email}`}>Revoke</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </div>
  );
}

function Requests({ query, onInvite }: { query: ReturnType<typeof useQuery<{ items: AccessRequest[]; total: number }>>; onInvite: (r: AccessRequest) => void }) {
  const queryClient = useQueryClient();
  const dismiss = useMutation({ mutationFn: (id: string) => api.dismissAccessRequest(id), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["access-requests"] }) });
  const items = query.data?.items ?? [];
  return (
    <div className="card table-wrap">
      <QueryState isLoading={query.isLoading} error={query.error}>
        {items.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name="check-circle" /></span><h2>No open requests</h2><p>People who ask for access on the sign-up page appear here. Inviting them closes the request.</p></div> : (
          <table>
            <thead><tr><th>Requester</th><th>Organization</th><th>Message</th><th>Received</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}<div className="small muted">{r.email}</div></td>
                  <td>{r.organization_name}{r.website && <div className="small mono muted">{r.website}</div>}</td>
                  <td className="small">{r.message ?? <span className="muted">No message</span>}</td>
                  <td className="small muted">{fmtDateTime(r.created_at)}</td>
                  <td><div className="actions row-actions"><button type="button" className="primary" onClick={() => onInvite(r)}><Icon name="user-plus" />Invite</button><button type="button" onClick={() => dismiss.mutate(r.id)}>Dismiss</button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </div>
  );
}

function Accounts({ query }: { query: ReturnType<typeof useQuery<{ items: { id: string; kind: string; name: string; org_id: string | null; email_domain: string | null; active_users: number; pending_invitations: number; api_keys: number }[]; total: number }>> }) {
  const items = query.data?.items ?? [];
  return (
    <div className="card table-wrap">
      <QueryState isLoading={query.isLoading} error={query.error}>
        <table>
          <thead><tr><th>Account</th><th>Kind</th><th>Email domain</th><th>Active users</th><th>Pending invitations</th><th>API keys</th></tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td>{a.org_id ? <Link to={`/organizations/${a.org_id}`}>{a.name}</Link> : a.name}</td>
                <td>{a.kind === "platform" ? <Badge tone="red">Platform</Badge> : <Badge tone="info">Organization</Badge>}</td>
                <td className="mono small">{a.email_domain ?? ""}</td>
                <td>{a.active_users}</td>
                <td>{a.pending_invitations}</td>
                <td>{a.api_keys}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </QueryState>
    </div>
  );
}
