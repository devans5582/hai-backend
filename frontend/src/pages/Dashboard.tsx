import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { FrameworkVisual } from "../components/FrameworkVisual";
import { TableDate } from "../components/TableDate";
import { Badge, QueryState } from "../components/widgets";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtNum, label, lifecycleGroup, toneForLifecycle, toneForOutcome } from "../lib/format";
import { useMe } from "../lib/me";

type Filter = "all" | "active" | "completed" | "attention";
type View = "organizations" | "runs";
const FILTERS: { id: Filter; label: string }[] = [{ id: "all", label: "All" }, { id: "active", label: "In progress" }, { id: "completed", label: "Completed" }, { id: "attention", label: "Needs attention" }];

function matches(filter: Filter, state: string): boolean {
  const group = lifecycleGroup(state);
  return filter === "all" || (filter === "active" && group.inProgress) || (filter === "completed" && group.completed) || (filter === "attention" && group.attention);
}

export function Dashboard() {
  const { apiKey, reviewerToken, session } = useAuth();
  const { me, capabilities } = useMe();
  const connected = !!(apiKey || reviewerToken || session);
  const organizationView = capabilities.organizationAccount;
  const canStart = !me || capabilities.startAssessments;
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<View>("organizations");
  const [offset, setOffset] = useState(0);
  const grouped = view === "organizations";
  const overview = useQuery({ queryKey: ["organizations-overview", offset], queryFn: () => api.organizationsOverview({ limit: 50, offset }), enabled: connected && grouped, refetchInterval: connected ? 15000 : false });
  const assessments = useQuery({ queryKey: ["assessments", offset], queryFn: () => api.listAssessments({ limit: 50, offset }), enabled: connected && !grouped, refetchInterval: connected ? 15000 : false });
  const tasks = useQuery({ queryKey: ["tasks", "open"], queryFn: () => api.listTasks({ status: "open" }), enabled: connected });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const needle = search.trim().toLowerCase();

  const rows = overview.data?.items ?? [];
  const filteredRows = rows.filter((row) => {
    const text = `${row.organization.display_name} ${row.organization.primary_domain} ${row.latest?.id ?? ""}`.toLowerCase();
    return text.includes(needle) && (!row.latest || matches(filter, row.latest.lifecycle_state));
  });
  const items = assessments.data?.items ?? [];
  const filteredRuns = items.filter((a) => `${a.submitted_domain} ${a.id}`.toLowerCase().includes(needle) && matches(filter, a.lifecycle_state));

  const active = grouped ? overview : assessments;
  const available = connected && !!active.data && !active.error;
  const total = grouped ? overview.data?.total ?? 0 : assessments.data?.total ?? 0;
  const inProgress = grouped ? rows.filter((row) => row.latest && lifecycleGroup(row.latest.lifecycle_state).inProgress).length : items.filter((a) => lifecycleGroup(a.lifecycle_state).inProgress).length;
  const shown = grouped ? filteredRows.length : filteredRuns.length;
  const pageSize = grouped ? rows.length : items.length;
  const stats: { label: string; value: string | number; detail: string; icon: IconName; color: string; to?: string }[] = [
    { label: grouped ? "Organizations assessed" : "Assessment runs", value: available ? total : "—", detail: grouped ? "Latest assessment for each organization" : "Every run, including earlier versions", icon: grouped ? "building" : "file", color: "red" },
    { label: "In progress", value: available ? inProgress : "—", detail: grouped ? "Running in the current page" : "In the current 50 runs", icon: "clock", color: "amber" },
    { label: "Awaiting review", value: tasks.data && !tasks.error ? tasks.data.total : "—", detail: tasks.error ? "Review queue unavailable" : "Open tasks in the review queue", icon: "reviews", color: "blue", to: "/reviews" },
    { label: "Platform status", value: health.data ? (health.data.status === "ok" ? "Operational" : health.data.status) : health.error ? "Unavailable" : "Checking", detail: health.data ? "Connected to the HAI API" : health.error ? "Unable to reach the HAI API" : "Checking the HAI API", icon: "activity", color: health.data?.status === "ok" ? "green" : "neutral" },
  ];
  const emptyTitle = (grouped ? rows.length : items.length) ? "No matching assessments" : canStart ? "Ready for your first assessment?" : "No reports yet";
  const emptyBody = (grouped ? rows.length : items.length) ? "Try another organization, domain or filter." : canStart ? "Start with an organization and its website. We’ll gather the evidence from there." : "Reports appear here once Humaital has assessed your organization.";
  return (
    <div className="stack dashboard">
      <div className="page-head">
        <div><span className="eyebrow">{organizationView ? me?.account?.name : "Your governance workspace"}</span><h1>{organizationView ? "Your reports" : "Dashboard"}</h1><p className="page-description">{organizationView ? "Your assessments, results, and the evidence behind every version." : "A clearer view of AI governance, backed by evidence."}</p></div>
        {canStart && <Link className="btn primary" to="/assessments/new"><Icon name="plus" />New assessment</Link>}
      </div>
      <section className="welcome-panel" aria-labelledby="welcome-title">
        <div className="welcome-copy"><span className="eyebrow"><span className="welcome-kicker-line" />Human Alignment Index</span><h2 id="welcome-title">Good governance starts<br className="desktop-break" /> with <em>a clear picture.</em></h2><p>Turn public evidence into a transparent assessment of how an organization governs AI.</p><Link className="text-link" to="/ontology">Explore the six pillars <Icon name="arrow-right" /></Link></div>
        <FrameworkVisual />
      </section>
      <div className="stats-grid">{stats.map((stat) => <div className="card stat" key={stat.label}><div className="stat-top"><span>{stat.label}</span><span className={`stat-icon ${stat.color}`}><Icon name={stat.icon} /></span></div><span className={`value ${stat.label === "Platform status" ? "status-value" : ""}`}>{stat.label === "Platform status" && <span className={`status-dot ${health.data?.status === "ok" ? "ok" : ""}`} />}{stat.value}</span><span className="stat-detail">{stat.to ? <Link to={stat.to}>{stat.detail}<Icon name="arrow-right" /></Link> : stat.detail}</span></div>)}</div>
      <div className="dashboard-columns">
        <section className="card assessments-card" aria-labelledby="recent">
          <div className="card-heading"><div><h2 id="recent">{grouped ? "Organizations" : "Assessment runs"}<span className="count-tag">{available ? total : "—"}</span></h2><p className="muted small">{grouped ? "Latest results at a glance. Open an organization to explore its assessment history." : "All assessment versions, with the most recent first."}</p></div>{available && <span className="live-label"><span className="status-dot" />Auto-updating</span>}</div>
          <div className="assessment-toolbar">
            <div className="assessment-controls">
              <div className="search-input">
                <Icon name="search" />
                <label className="sr-only" htmlFor="assessment-search">Search assessments</label>
                <input id="assessment-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={grouped ? "Search organization or domain…" : "Search domain or ID…"} />
              </div>
              <div className="filter-group view-switch" role="group" aria-label="View">
                <button type="button" aria-pressed={grouped} onClick={() => { setView("organizations"); setOffset(0); }}><Icon name="building" />By organization</button>
                <button type="button" aria-pressed={!grouped} onClick={() => { setView("runs"); setOffset(0); }}><Icon name="layers" />All runs</button>
              </div>
            </div>
            <div className="filter-group assessment-filters" role="group" aria-label="Filter assessments">
              {FILTERS.map((f) => <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>{f.label}</button>)}
            </div>
          </div>
          {!connected ? <div className="empty-state"><span className="empty-icon"><Icon name="key" /></span><h3>Your workspace starts here</h3><p>Connect an API key or reviewer token to see your assessments and start exploring results.</p><Link className="btn primary" to="/login">Connect your workspace<Icon name="arrow-right" /></Link><span className="empty-footnote"><Icon name="lock" />Credentials stay in your browser</span></div> : <QueryState isLoading={active.isLoading} error={active.error}>
            {shown === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name={pageSize ? "search" : "file"} /></span><h3>{emptyTitle}</h3><p>{emptyBody}</p>{pageSize ? <button type="button" onClick={() => { setSearch(""); setFilter("all"); }}>Clear filters</button> : canStart ? <Link className="btn primary" to="/assessments/new"><Icon name="plus" />New assessment</Link> : null}</div> : grouped ? (
              <div className="table-wrap assessment-table-wrap" role="region" aria-label="Organization assessments" tabIndex={0}>
                <table className="data-table overview-table">
                  <caption className="sr-only">Latest assessment by organization</caption>
                  <colgroup>
                    <col className="organization-column" />
                    <col className="version-column" />
                    <col className="status-column" />
                    <col className="score-column" />
                    <col className="outcome-column" />
                    <col className="date-column" />
                    <col className="action-column" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Organization</th>
                      <th scope="col">Version</th>
                      <th scope="col">Status</th>
                      <th scope="col" className="numeric-cell">HAI Score</th>
                      <th scope="col">Outcome</th>
                      <th scope="col">Assessed</th>
                      <th scope="col" className="action-cell"><span className="sr-only">Open</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((row) => (
                      <tr key={row.organization.id}>
                        <td>
                          <Link className="assessment-name" to={`/organizations/${row.organization.id}`}>
                            <span className="domain-avatar" aria-hidden="true">{row.organization.display_name[0]?.toUpperCase() ?? "O"}</span>
                            <span className="table-identity">
                              <strong>{row.organization.display_name}</strong>
                              <small>{row.organization.primary_domain}{row.organization.industry_label ? ` · ${row.organization.industry_label}` : ""}</small>
                            </span>
                          </Link>
                        </td>
                        <td>{row.latest ? <span className="version-pill" title={`${row.versions} assessment${row.versions === 1 ? "" : "s"} of this organization`}>v{row.latest.version}<small>of {row.versions}</small></span> : <span className="table-placeholder">Not assessed</span>}</td>
                        <td className="status-cell">{row.latest ? <Badge tone={toneForLifecycle(row.latest.lifecycle_state)}>{row.latest.lifecycle_label}</Badge> : <span className="table-placeholder">—</span>}</td>
                        <td className="numeric-cell">
                          {row.result ? (
                            <div className="table-score">
                              <strong>{fmtNum(row.result.hai_score)}</strong>
                              {row.score_delta !== null && <small className={`delta ${row.score_delta >= 0 ? "up" : "down"}`} aria-label={`change from previous version ${row.score_delta >= 0 ? "+" : ""}${row.score_delta}`}>{row.score_delta >= 0 ? "+" : ""}{row.score_delta}</small>}
                            </div>
                          ) : <span className="table-placeholder">n/a</span>}
                        </td>
                        <td className="outcome-cell">{row.result ? <Badge tone={toneForOutcome(row.result.outcome_status)}>{row.result.outcome_label}</Badge> : <span className="table-placeholder">{row.latest ? "No result yet" : "—"}</span>}</td>
                        <td><TableDate value={row.latest?.created_at} /></td>
                        <td className="action-cell">{row.latest && <Link className="icon-button table-row-action" to={`/assessments/${row.latest.id}`} aria-label={`View latest assessment for ${row.organization.display_name}`}><Icon name="arrow-right" /></Link>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="table-wrap assessment-table-wrap" role="region" aria-label="Assessment runs" tabIndex={0}>
                <table className="data-table runs-table">
                  <caption className="sr-only">All assessment runs, newest first</caption>
                  <colgroup>
                    <col className="organization-column" />
                    <col className="status-column" />
                    <col className="context-column" />
                    <col className="date-column" />
                    <col className="action-column" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">Organization / domain</th>
                      <th scope="col">Status</th>
                      <th scope="col">Context</th>
                      <th scope="col">Created</th>
                      <th scope="col" className="action-cell"><span className="sr-only">View assessment</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRuns.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <Link className="assessment-name" to={`/assessments/${a.id}`}>
                            <span className="domain-avatar" aria-hidden="true">{a.submitted_domain[0]?.toUpperCase() ?? "O"}</span>
                            <span className="table-identity"><strong>{a.submitted_domain}</strong><small className="assessment-id"><span>ID</span><span className="mono">{a.id.slice(0, 8)}</span></small></span>
                          </Link>
                        </td>
                        <td className="status-cell"><Badge tone={toneForLifecycle(a.lifecycle_state)}>{a.lifecycle_label}</Badge></td>
                        <td><div className="table-context"><span>{label("stage_band", a.stage_band)}</span><small>{label("size_band", a.size_band)}</small></div></td>
                        <td><TableDate value={a.created_at} /></td>
                        <td className="action-cell"><Link className="icon-button table-row-action" to={`/assessments/${a.id}`} aria-label={`View assessment for ${a.submitted_domain}`}><Icon name="arrow-right" /></Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {available && shown > 0 && <p className={`table-scroll-hint ${grouped ? "overview-scroll-hint" : "runs-scroll-hint"}`}><Icon name="arrow-right" />Scroll horizontally to see all columns</p>}
            {available && <div className="table-footer"><span>{search || filter !== "all" ? `${shown} matching in this page` : `Showing ${pageSize ? offset + 1 : 0}–${offset + pageSize} of ${total}`}</span>{(total > 50 || offset > 0) && <div className="actions"><button type="button" onClick={() => setOffset(Math.max(0, offset - 50))} disabled={offset === 0}>Previous</button><button type="button" onClick={() => setOffset(offset + 50)} disabled={offset + 50 >= total}>Next</button></div>}<span>Updates automatically</span></div>}
          </QueryState>}
        </section>
        <aside className="dashboard-aside">
          <section className="card workflow-card"><span className="eyebrow">A traceable process</span><h2>From evidence to insight</h2><ol className="workflow-list"><li><span className="workflow-number">1</span><div><h3>Collect evidence</h3><p>Public policies, reports, and governance practices.</p></div></li><li><span className="workflow-number">2</span><div><h3>Evaluate consistently</h3><p>20 criteria across six pillars, assessed by defined rules.</p></div></li><li><span className="workflow-number">3</span><div><h3>Review with confidence</h3><p>Follow every result back to its source.</p></div></li></ol><Link className="text-link" to="/ontology">See the methodology<Icon name="arrow-right" /></Link></section>
          <Link to="/verify" className="verify-shortcut"><span className="shortcut-icon"><Icon name="shield" /></span><div><strong>Check a certificate</strong><p>Verify a HAI Score certificate.<br />Public, no sign-in needed.</p></div><Icon name="arrow-right" /></Link>
        </aside>
      </div>
    </div>
  );
}
