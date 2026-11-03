import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "../components/Icon";
import { Badge, QueryState } from "../components/widgets";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime, label, toneForLifecycle } from "../lib/format";

const IN_PROGRESS_STATES = new Set(["queued", "acquiring", "evaluating", "awaiting_review"]);

type Filter = "all" | "active" | "completed" | "attention";
const FILTERS: { id: Filter; label: string }[] = [{ id: "all", label: "All assessments" }, { id: "active", label: "In progress" }, { id: "completed", label: "Completed" }, { id: "attention", label: "Needs attention" }];

export function Dashboard() {
  const { apiKey, reviewerToken } = useAuth();
  const connected = !!(apiKey || reviewerToken);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [offset, setOffset] = useState(0);
  const assessments = useQuery({ queryKey: ["assessments", offset], queryFn: () => api.listAssessments({ limit: 50, offset }), enabled: connected, refetchInterval: connected ? 15000 : false });
  const tasks = useQuery({ queryKey: ["tasks", "open"], queryFn: () => api.listTasks({ status: "open" }), enabled: connected });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const items = assessments.data?.items ?? [];
  const inProgress = items.filter((a) => IN_PROGRESS_STATES.has(a.lifecycle_state)).length;
  const filtered = items.filter((a) => {
    const matchesSearch = `${a.submitted_domain} ${a.id}`.toLowerCase().includes(search.trim().toLowerCase());
    const matchesFilter = filter === "all" || (filter === "active" && IN_PROGRESS_STATES.has(a.lifecycle_state)) || (filter === "completed" && ["completed", "completed_unverified"].includes(a.lifecycle_state)) || (filter === "attention" && ["failed", "awaiting_review"].includes(a.lifecycle_state));
    return matchesSearch && matchesFilter;
  });
  const available = connected && !!assessments.data && !assessments.error;
  const stats: { label: string; value: string | number; detail: string; icon: IconName; color: string; to?: string }[] = [
    { label: "Total assessments", value: available ? assessments.data!.total : "—", detail: "Across your workspace", icon: "file", color: "red" },
    { label: "In progress", value: available ? inProgress : "—", detail: "In the current 50 assessments", icon: "clock", color: "amber" },
    { label: "Awaiting review", value: tasks.data && !tasks.error ? tasks.data.total : "—", detail: tasks.error ? "Review queue unavailable" : "Open tasks in the review queue", icon: "reviews", color: "blue", to: "/reviews" },
    { label: "Platform status", value: health.data ? (health.data.status === "ok" ? "Operational" : health.data.status) : health.error ? "Unavailable" : "Checking", detail: health.data ? "Connected to the HAI API" : health.error ? "Unable to reach the HAI API" : "Checking the HAI API", icon: "activity", color: health.data?.status === "ok" ? "green" : "neutral" },
  ];
  return (
    <div className="stack dashboard">
      <div className="page-head">
        <div><span className="eyebrow">Workspace overview</span><h1>Dashboard</h1><p className="page-description">A clearer view of your AI governance assessments.</p></div>
        <Link className="btn primary" to="/assessments/new"><Icon name="plus" />New assessment</Link>
      </div>
      <section className="welcome-panel" aria-labelledby="welcome-title">
        <div className="welcome-copy"><span className="eyebrow">Human Alignment Index</span><h2 id="welcome-title">Good governance starts<br className="desktop-break" /> with a clear picture.</h2><p>Turn public evidence into a transparent assessment of how an organization governs AI.</p><Link className="text-link" to="/ontology">Explore the six pillars <Icon name="arrow-right" /></Link></div>
        <div className="pillar-visual" aria-hidden="true"><div className="pillar-orbit"><div className="orbit-center"><Icon name="shield" /><span>HAI Score</span></div><span className="orbit-label orbit-1">Trust</span><span className="orbit-label orbit-2">Accountability</span><span className="orbit-label orbit-3">Purpose</span><span className="orbit-label orbit-4">Safety</span><span className="orbit-label orbit-5">Transparency</span><span className="orbit-label orbit-6">Impact</span></div></div>
      </section>
      <div className="stats-grid">{stats.map((stat) => <div className="card stat" key={stat.label}><div className="stat-top"><span>{stat.label}</span><span className={`stat-icon ${stat.color}`}><Icon name={stat.icon} /></span></div><span className={`value ${stat.label === "Platform status" ? "status-value" : ""}`}>{stat.label === "Platform status" && <span className={`status-dot ${health.data?.status === "ok" ? "ok" : ""}`} />}{stat.value}</span><span className="stat-detail">{stat.to ? <Link to={stat.to}>{stat.detail}<Icon name="arrow-right" /></Link> : stat.detail}</span></div>)}</div>
      <div className="dashboard-columns">
        <section className="card assessments-card" aria-labelledby="recent">
          <div className="card-heading"><div><h2 id="recent">Recent assessments</h2><p className="muted small">Track progress and explore the evidence behind your results.</p></div><span className="count-tag">{available ? assessments.data!.total : "—"}</span></div>
          <div className="assessment-toolbar"><div className="filter-group" role="group" aria-label="Filter assessments">{FILTERS.map((f) => <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>{f.label}</button>)}</div><div className="search-input"><Icon name="search" /><label className="sr-only" htmlFor="assessment-search">Search assessments</label><input id="assessment-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search domain or ID…" /></div></div>
          {!connected ? <div className="empty-state"><span className="empty-icon"><Icon name="key" /></span><h3>Your workspace starts here</h3><p>Connect an API key or reviewer token to see your assessments and start exploring results.</p><Link className="btn primary" to="/settings">Connect your workspace<Icon name="arrow-right" /></Link><span className="empty-footnote"><Icon name="lock" />Credentials stay in your browser</span></div> : <QueryState isLoading={assessments.isLoading} error={assessments.error}>
            {filtered.length === 0 ? <div className="empty-state"><span className="empty-icon"><Icon name={items.length ? "search" : "file"} /></span><h3>{items.length ? "No matching assessments" : "Ready for your first assessment?"}</h3><p>{items.length ? "Try another domain or choose a different filter." : "Start with an organization and its website. We’ll gather the evidence from there."}</p>{items.length ? <button type="button" onClick={() => { setSearch(""); setFilter("all"); }}>Clear filters</button> : <Link className="btn primary" to="/assessments/new"><Icon name="plus" />New assessment</Link>}</div> : <div className="table-wrap"><table><thead><tr><th>Organization / domain</th><th>Status</th><th>Context</th><th>Created</th><th><span className="sr-only">View assessment</span></th></tr></thead><tbody>{filtered.map((a) => <tr key={a.id}><td><Link className="assessment-name" to={`/assessments/${a.id}`}><span className="domain-avatar">{a.submitted_domain[0]?.toUpperCase() ?? "O"}</span><span>{a.submitted_domain}<small className="mono">{a.id.slice(0, 8)}</small></span></Link></td><td><Badge tone={toneForLifecycle(a.lifecycle_state)}>{a.lifecycle_label}</Badge></td><td><span>{label("stage_band", a.stage_band)}</span><div className="small muted">{label("size_band", a.size_band)}</div></td><td className="small muted">{fmtDateTime(a.created_at)}</td><td><Link className="icon-button" to={`/assessments/${a.id}`} aria-label={`View assessment for ${a.submitted_domain}`}><Icon name="arrow-right" /></Link></td></tr>)}</tbody></table></div>}
            {available && <div className="table-footer"><span>{search || filter !== "all" ? `${filtered.length} matching in this page` : `Showing ${items.length ? offset + 1 : 0}–${offset + items.length} of ${assessments.data!.total}`}</span>{(assessments.data!.total > 50 || offset > 0) && <div className="actions"><button type="button" onClick={() => setOffset(Math.max(0, offset - 50))} disabled={offset === 0}>Previous</button><button type="button" onClick={() => setOffset(offset + 50)} disabled={offset + 50 >= assessments.data!.total}>Next</button></div>}<span>Updates automatically</span></div>}
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
