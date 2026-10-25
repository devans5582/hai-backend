import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, QueryState } from "../components/widgets";
import { api } from "../lib/api";
import { fmtDate, fmtDateTime, fmtNum, label, toneForLifecycle } from "../lib/format";

export function Organizations() {
  const [q, setQ] = useState("");
  const orgs = useQuery({ queryKey: ["organizations", q], queryFn: () => api.listOrganizations(q || undefined) });
  const bench = useQuery({ queryKey: ["benchmarks"], queryFn: api.benchmarks });
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Organizations</h1>
        <div className="field" style={{ margin: 0 }}>
          <label htmlFor="q" className="sr-only">
            Search organizations
          </label>
          <input id="q" placeholder="Search by name or domain" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <div className="card table-wrap">
        <QueryState isLoading={orgs.isLoading} error={orgs.error}>
          <table>
            <thead>
              <tr>
                <th>Organization</th>
                <th>Domain</th>
                <th>Industry</th>
                <th>Identifiers</th>
              </tr>
            </thead>
            <tbody>
              {(orgs.data?.items ?? []).map((o) => (
                <tr key={o.id}>
                  <td>
                    <Link to={`/organizations/${o.id}`}>{o.display_name}</Link>
                  </td>
                  <td className="mono">{o.primary_domain}</td>
                  <td>{o.industry_code ?? ""}</td>
                  <td className="small">
                    {o.identifiers_verified ? <Badge tone="ok">verified</Badge> : <Badge>unverified</Badge>}{" "}
                    {Object.entries(o.identifiers)
                      .filter(([, v]) => v)
                      .map(([k, v]) => `${k} ${v}`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {orgs.data?.total === 0 && <p className="muted">No organizations yet.</p>}
        </QueryState>
      </div>
      <section className="card table-wrap" aria-labelledby="bench">
        <h2 id="bench">Peer benchmarks</h2>
        <p className="muted small">Latest result per organization, grouped by industry, stage and size. Access-limited runs are excluded.</p>
        <QueryState isLoading={bench.isLoading} error={bench.error}>
          {(bench.data?.items.length ?? 0) === 0 ? (
            <p className="muted">No completed assessments to compare yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Industry</th>
                  <th>Stage</th>
                  <th>Size</th>
                  <th>Organizations</th>
                  <th>Average score</th>
                  <th>Average confidence</th>
                </tr>
              </thead>
              <tbody>
                {bench.data?.items.map((b) => (
                  <tr key={`${b.industry}-${b.stage_band}-${b.size_band}`}>
                    <td>{b.industry ?? "unspecified"}</td>
                    <td>{label("stage_band", b.stage_band)}</td>
                    <td>{label("size_band", b.size_band)}</td>
                    <td>{b.organizations}</td>
                    <td>{fmtNum(b.average_score)}</td>
                    <td>{fmtNum(b.average_confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryState>
      </section>
    </div>
  );
}

export function OrganizationDetail() {
  const { id = "" } = useParams();
  const org = useQuery({ queryKey: ["organization", id], queryFn: () => api.getOrganization(id) });
  const assessments = useQuery({ queryKey: ["org-assessments", id], queryFn: () => api.orgAssessments(id) });
  const [offset, setOffset] = useState(0);
  const evidence = useQuery({ queryKey: ["org-evidence", id, offset], queryFn: () => api.orgEvidence(id, { limit: 20, offset }) });
  return (
    <QueryState isLoading={org.isLoading} error={org.error}>
      {org.data && (
        <div className="stack">
          <div className="page-head">
            <div>
              <h1>{org.data.display_name}</h1>
              <div className="row small muted">
                <span className="mono">{org.data.primary_domain}</span>
                <span>{org.data.legal_name}</span>
                {org.data.identifiers_verified ? <Badge tone="ok">identifiers verified</Badge> : <Badge>identifiers unverified</Badge>}
                {org.data.entity_confidence !== null && <span>entity confidence {fmtNum(org.data.entity_confidence, 2)}</span>}
              </div>
            </div>
          </div>
          <section className="card table-wrap" aria-labelledby="org-assessments">
            <h2 id="org-assessments">Assessments</h2>
            <QueryState isLoading={assessments.isLoading} error={assessments.error}>
              <table>
                <thead>
                  <tr>
                    <th>Assessment</th>
                    <th>State</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {(assessments.data?.items ?? []).map((a) => (
                    <tr key={a.id}>
                      <td>
                        <Link to={`/assessments/${a.id}`}>{a.id.slice(0, 8)}</Link>
                      </td>
                      <td>
                        <Badge tone={toneForLifecycle(a.lifecycle_state)}>{a.lifecycle_label}</Badge>
                      </td>
                      <td>{fmtDateTime(a.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </QueryState>
          </section>
          <section className="card" aria-labelledby="ledger">
            <h2 id="ledger">Evidence ledger</h2>
            <QueryState isLoading={evidence.isLoading} error={evidence.error}>
              <p className="muted small">
                {evidence.data?.total ?? 0} links. Showing {offset + 1} to {Math.min(offset + 20, evidence.data?.total ?? 0)}.
              </p>
              {(evidence.data?.items ?? []).map((e) => (
                <div key={e.link_id} style={{ marginBottom: "0.75rem" }}>
                  <div className="row small">
                    <span className="mono">{e.criterion_code}</span>
                    <Badge tone={e.polarity === "supports" ? "ok" : e.polarity === "contradicts" ? "bad" : "info"}>{label("polarity", e.polarity)}</Badge>
                    <Badge tone={e.admissibility === "admissible" ? "ok" : "warn"}>{label("admissibility", e.admissibility)}</Badge>
                    <Badge>{label("maturity_rung", e.maturity_rung)}</Badge>
                  </div>
                  <blockquote className="quote">{e.quote}</blockquote>
                  <div className="small muted">
                    {e.publisher}, {e.published_at ? fmtDate(e.published_at) : "undated"},{" "}
                    <a href={e.canonical_url} target="_blank" rel="noreferrer">
                      source
                    </a>
                  </div>
                </div>
              ))}
              <div className="actions">
                <button type="button" onClick={() => setOffset(Math.max(0, offset - 20))} disabled={offset === 0}>
                  Previous
                </button>
                <button type="button" onClick={() => setOffset(offset + 20)} disabled={offset + 20 >= (evidence.data?.total ?? 0)}>
                  Next
                </button>
              </div>
            </QueryState>
          </section>
        </div>
      )}
    </QueryState>
  );
}
