import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Badge, QueryState } from "../components/widgets";
import { api } from "../lib/api";
import { fmtDateTime, toneForLifecycle } from "../lib/format";

export function Dashboard() {
  const navigate = useNavigate();
  const assessments = useQuery({ queryKey: ["assessments"], queryFn: () => api.listAssessments({ limit: 50 }) });
  const tasks = useQuery({ queryKey: ["tasks", "open"], queryFn: () => api.listTasks({ status: "open" }) });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const items = assessments.data?.items ?? [];
  const counts = items.reduce<Record<string, number>>((acc, a) => ({ ...acc, [a.lifecycle_state]: (acc[a.lifecycle_state] ?? 0) + 1 }), {});
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Dashboard</h1>
        <Link className="btn primary" to="/assessments/new">
          New assessment
        </Link>
      </div>
      <div className="grid">
        <div className="card stat">
          <span className="muted small">Assessments</span>
          <span className="value">{assessments.data?.total ?? "..."}</span>
        </div>
        <div className="card stat">
          <span className="muted small">Awaiting review</span>
          <span className="value">{counts["awaiting_review"] ?? 0}</span>
        </div>
        <div className="card stat">
          <span className="muted small">Open review tasks</span>
          <span className="value">{tasks.data?.total ?? (tasks.error ? "n/a" : "...")}</span>
        </div>
        <div className="card stat">
          <span className="muted small">API</span>
          <span className="value">{health.data ? health.data.status : health.error ? "down" : "..."}</span>
          <span className="muted small">{health.data ? `ontology ${health.data.ontology_version}, methodology ${health.data.methodology_version}` : ""}</span>
        </div>
      </div>
      <section className="card" aria-labelledby="recent">
        <h2 id="recent">Recent assessments</h2>
        <QueryState isLoading={assessments.isLoading} error={assessments.error}>
          {items.length === 0 ? (
            <p className="muted">No assessments yet.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>State</th>
                    <th>Stage / size</th>
                    <th>Created</th>
                    <th>Model</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => navigate(`/assessments/${a.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/assessments/${a.id}`)}>
                      <td>
                        <Link to={`/assessments/${a.id}`}>{a.submitted_domain}</Link>
                      </td>
                      <td>
                        <Badge tone={toneForLifecycle(a.lifecycle_state)}>{a.lifecycle_label}</Badge>
                      </td>
                      <td>
                        {a.stage_band} / {a.size_band}
                      </td>
                      <td>{fmtDateTime(a.created_at)}</td>
                      <td className="mono small">{a.versions["model"]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryState>
      </section>
    </div>
  );
}
