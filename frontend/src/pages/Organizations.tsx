import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { TableDate } from "../components/TableDate";
import { Badge, QueryState } from "../components/widgets";
import { api } from "../lib/api";
import { fmtDate, fmtNum, label, toneForLifecycle, toneForOutcome } from "../lib/format";

export function Organizations() {
  const [q, setQ] = useState("");
  const orgs = useQuery({ queryKey: ["organizations", q], queryFn: () => api.listOrganizations(q || undefined) });
  const bench = useQuery({ queryKey: ["benchmarks"], queryFn: api.benchmarks });
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <span className="eyebrow">Your organization directory</span>
          <h1>Organizations</h1>
          <p className="page-description">Explore assessment history, traceable evidence, and peer benchmarks.</p>
        </div>
        <div className="search-input">
          <Icon name="search" />
          <label htmlFor="q" className="sr-only">
            Search organizations
          </label>
          <input id="q" type="search" placeholder="Search by name or domain" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <div className="card data-table-card">
        <QueryState isLoading={orgs.isLoading} error={orgs.error}>
          {(orgs.data?.items.length ?? 0) === 0 ? (
            <div className="empty-state">
              <span className="empty-icon"><Icon name={q ? "search" : "building"} /></span>
              <h2>{q ? "No matching organizations" : "Your directory starts here"}</h2>
              <p>{q ? "Try another name or domain to find the organization you need." : "Start an assessment to add an organization and build its evidence history."}</p>
              {q ? <button type="button" onClick={() => setQ("")}>Clear search</button> : <Link className="btn primary" to="/assessments/new"><Icon name="plus" /> New assessment</Link>}
            </div>
          ) : <div className="table-wrap" role="region" aria-label="Organization directory" tabIndex={0}><table className="data-table directory-table" aria-label="Organization directory">
            <colgroup>
              <col style={{ width: "28%" }} />
              <col style={{ width: "23%" }} />
              <col style={{ width: "20%" }} />
              <col style={{ width: "29%" }} />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Organization</th>
                <th scope="col">Domain</th>
                <th scope="col">Industry</th>
                <th scope="col">Identifiers</th>
              </tr>
            </thead>
            <tbody>
              {(orgs.data?.items ?? []).map((o) => (
                <tr key={o.id}>
                  <td>
                    <Link className="assessment-name" to={`/organizations/${o.id}`}><span className="domain-avatar" aria-hidden="true">{o.display_name[0]?.toUpperCase() ?? "O"}</span><span>{o.display_name}</span></Link>
                  </td>
                  <td className="mono">{o.primary_domain}</td>
                  <td>{label("industry", o.industry_code)}</td>
                  <td className="identifier-cell">
                    {o.identifiers_verified ? <Badge tone="ok">Verified</Badge> : <Badge>Unverified</Badge>}
                    <span className="table-secondary">{Object.entries(o.identifiers)
                      .filter(([, v]) => v)
                      .map(([k, v]) => `${k} ${v}`)
                      .join(", ")}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>}
        </QueryState>
      </div>
      <section className="card data-table-card" aria-labelledby="bench">
        <div className="data-table-heading"><div><h2 id="bench">Peer benchmarks</h2>
        <p className="muted small">Latest result per organization, grouped by industry, stage and size. Access-limited runs are excluded.</p></div></div>
        <QueryState isLoading={bench.isLoading} error={bench.error}>
          {(bench.data?.items.length ?? 0) === 0 ? (
            <div className="empty-state">
              <span className="empty-icon"><Icon name="layers" /></span>
              <h3>See how peers compare</h3>
              <p>Benchmarks will appear here as eligible assessments are completed.</p>
              <Link className="text-link" to="/assessments/new">Start an assessment <Icon name="arrow-right" /></Link>
            </div>
          ) : (
            <div className="table-wrap" role="region" aria-labelledby="bench" tabIndex={0}><table className="data-table benchmark-table" aria-labelledby="bench">
              <colgroup>
                <col style={{ width: "22%" }} />
                <col style={{ width: "17%" }} />
                <col style={{ width: "18%" }} />
                <col style={{ width: "13%" }} />
                <col style={{ width: "14%" }} />
                <col style={{ width: "16%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Industry</th>
                  <th scope="col">Stage</th>
                  <th scope="col">Size</th>
                  <th scope="col" className="numeric-cell">Organizations</th>
                  <th scope="col" className="numeric-cell">Average score</th>
                  <th scope="col" className="numeric-cell">Average confidence</th>
                </tr>
              </thead>
              <tbody>
                {bench.data?.items.map((b) => (
                  <tr key={`${b.industry}-${b.stage_band}-${b.size_band}`}>
                    <td>{b.industry ? label("industry", b.industry) : "unspecified"}</td>
                    <td>{label("stage_band", b.stage_band)}</td>
                    <td>{label("size_band", b.size_band)}</td>
                    <td className="numeric-cell">{b.organizations}</td>
                    <td className="numeric-cell">{fmtNum(b.average_score)}</td>
                    <td className="numeric-cell">{fmtNum(b.average_confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </QueryState>
      </section>
    </div>
  );
}

export function OrganizationDetail() {
  const { id = "" } = useParams();
  const org = useQuery({ queryKey: ["organization", id], queryFn: () => api.getOrganization(id) });
  const history = useQuery({ queryKey: ["org-history", id], queryFn: () => api.organizationHistory(id) });
  const [offset, setOffset] = useState(0);
  const evidence = useQuery({ queryKey: ["org-evidence", id, offset], queryFn: () => api.orgEvidence(id, { limit: 20, offset }) });
  return (
    <QueryState isLoading={org.isLoading} error={org.error}>
      {org.data && (
        <div className="stack">
          <Link className="text-link" to="/organizations"><Icon name="arrow-left" /> All organizations</Link>
          <div className="page-head">
            <div>
              <span className="eyebrow">Organization profile</span>
              <h1>{org.data.display_name}</h1>
              <div className="row small muted">
                <span className="mono">{org.data.primary_domain}</span>
                <span>{org.data.legal_name}</span>
                {org.data.industry_code && <span>{label("industry", org.data.industry_code)}</span>}
                {org.data.identifiers_verified ? <Badge tone="ok">Identifiers verified</Badge> : <Badge>Identifiers unverified</Badge>}
                {org.data.entity_confidence !== null && <span>Entity confidence {fmtNum(org.data.entity_confidence, 2)}</span>}
              </div>
            </div>
          </div>
          <section className="card data-table-card" aria-labelledby="org-assessments">
            <div className="data-table-heading"><div><h2 id="org-assessments">Assessment history</h2><p className="muted small">One organization, every assessment as a numbered version. The latest version is what the dashboard shows; earlier versions stay readable and are never edited.</p></div>{history.data && <span className="count-tag">{history.data.total} version{history.data.total === 1 ? "" : "s"}</span>}</div>
            <QueryState isLoading={history.isLoading} error={history.error}>
              {(history.data?.items.length ?? 0) === 0 ? (
                <div className="empty-state">
                  <span className="empty-icon"><Icon name="file" /></span>
                  <h3>No assessments yet</h3>
                  <p>Start an assessment to understand this organization's AI governance.</p>
                  <Link className="btn primary" to="/assessments/new"><Icon name="plus" /> New assessment</Link>
                </div>
              ) : <div className="table-wrap" role="region" aria-labelledby="org-assessments" tabIndex={0}><table className="data-table history-table" aria-labelledby="org-assessments">
                <colgroup>
                  <col style={{ width: "15%" }} />
                  <col style={{ width: "19%" }} />
                  <col style={{ width: "10%" }} />
                  <col style={{ width: "22%" }} />
                  <col style={{ width: "12%" }} />
                  <col style={{ width: "15%" }} />
                  <col style={{ width: "7%" }} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Version</th>
                    <th scope="col">State</th>
                    <th scope="col" className="numeric-cell">HAI Score</th>
                    <th scope="col">Outcome</th>
                    <th scope="col">Methodology</th>
                    <th scope="col">Assessed</th>
                    <th scope="col" className="action-cell"><span className="sr-only">Open</span></th>
                  </tr>
                </thead>
                <tbody>
                  {(history.data?.items ?? []).map((v) => (
                    <tr key={v.assessment.id} className={v.is_latest ? "row-latest" : ""}>
                      <td><Link to={`/assessments/${v.assessment.id}`} className="version-link">v{v.version}{v.is_latest && <Badge tone="red">Latest</Badge>}</Link><div className="small muted mono">{v.assessment.id.slice(0, 8)}</div></td>
                      <td><Badge tone={toneForLifecycle(v.assessment.lifecycle_state)}>{v.assessment.lifecycle_label}</Badge></td>
                      <td className="numeric-cell">{v.result ? fmtNum(v.result.hai_score) : <span className="muted">n/a</span>}</td>
                      <td className="outcome-cell">{v.result ? <Badge tone={toneForOutcome(v.result.outcome_status)}>{v.result.outcome_label}</Badge> : <span className="muted small">No result yet</span>}</td>
                      <td className="small muted">{v.assessment.methodology_version} / {v.assessment.ruleset_version}</td>
                      <td><TableDate value={v.assessment.created_at} /></td>
                      <td className="action-cell"><Link className="icon-button table-row-action" to={`/assessments/${v.assessment.id}`} aria-label={`Open version ${v.version}`}><Icon name="arrow-right" /></Link></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>}
            </QueryState>
          </section>
          <section className="card" aria-labelledby="ledger">
            <h2 id="ledger">Evidence ledger</h2>
            <QueryState isLoading={evidence.isLoading} error={evidence.error}>
              {(evidence.data?.items.length ?? 0) === 0 ? (
                <div className="empty-state">
                  <span className="empty-icon"><Icon name="file" /></span>
                  <h3>{offset === 0 ? "No evidence links yet" : "No evidence on this page"}</h3>
                  <p>{offset === 0 ? "Collected evidence will appear here as assessments progress." : "Return to the previous page to explore the available evidence."}</p>
                  {offset === 0 && <Link className="text-link" to="/assessments/new">Start an assessment <Icon name="arrow-right" /></Link>}
                </div>
              ) : <p className="muted small">
                {evidence.data?.total ?? 0} links. Showing {offset + 1} to {Math.min(offset + (evidence.data?.items.length ?? 0), evidence.data?.total ?? 0)}.
              </p>}
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
              {((evidence.data?.total ?? 0) > 20 || offset > 0) && <div className="actions">
                <button type="button" onClick={() => setOffset(Math.max(0, offset - 20))} disabled={offset === 0}>
                  Previous
                </button>
                <button type="button" onClick={() => setOffset(offset + 20)} disabled={offset + 20 >= (evidence.data?.total ?? 0)}>
                  Next
                </button>
              </div>}
            </QueryState>
          </section>
        </div>
      )}
    </QueryState>
  );
}
