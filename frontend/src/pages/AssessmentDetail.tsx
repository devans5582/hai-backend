import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { TraceDrawer } from "../components/TraceDrawer";
import { Badge, CoverageStrip, PillarBars, QueryState, ScoreDial, Tabs } from "../components/widgets";
import { api, ApiRequestError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { connectorLabel } from "../lib/connectors";
import { LIFECYCLE_UI, fmtDate, fmtDateTime, fmtNum, label, toneForLifecycle, toneForOutcome } from "../lib/format";

type Tab = "overview" | "criteria" | "sources" | "reviews";

export function AssessmentDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { reviewer } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [traceCode, setTraceCode] = useState<string | null>(null);
  const assessment = useQuery({ queryKey: ["assessment", id], queryFn: () => api.getAssessment(id), refetchInterval: (q) => (q.state.data && LIFECYCLE_UI[q.state.data.lifecycle_state]?.polling ? 3000 : false) });
  const report = useQuery({ queryKey: ["report", id, assessment.data?.lifecycle_state], queryFn: () => api.getReport(id), enabled: !!assessment.data });
  const runs = useQuery({ queryKey: ["runs", id, assessment.data?.lifecycle_state], queryFn: () => api.getConnectorRuns(id), enabled: !!assessment.data });
  const tasks = useQuery({ queryKey: ["tasks", id], queryFn: () => api.listTasks({ status: "all", assessment_id: id }), enabled: !!assessment.data });
  const invalidate = () => qc.invalidateQueries();
  const cancel = useMutation({ mutationFn: () => api.cancelAssessment(id), onSuccess: invalidate });
  const reassess = useMutation({ mutationFn: () => api.reassess(id), onSuccess: invalidate });
  const requestCert = useMutation({ mutationFn: () => api.requestCertification(id), onSuccess: invalidate });
  const a = assessment.data;
  const r = report.data;
  return (
    <QueryState isLoading={assessment.isLoading} error={assessment.error}>
      {a && (
        <div className="stack">
          <div className="page-head">
            <div>
              <h1>{r?.organization.name ?? a.submitted_domain}</h1>
              <div className="row small muted">
                <span className="mono">{a.submitted_domain}</span>
                <Badge tone={toneForLifecycle(a.lifecycle_state)}>{a.lifecycle_label}</Badge>
                <span>
                  {a.stage_band} / {a.size_band}
                </span>
                <span>created {fmtDateTime(a.created_at)}</span>
              </div>
            </div>
            <div className="actions">
              {LIFECYCLE_UI[a.lifecycle_state]?.cancel && (
                <button type="button" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                  Cancel
                </button>
              )}
              {LIFECYCLE_UI[a.lifecycle_state]?.reassess && (
                <button type="button" onClick={() => reassess.mutate()} disabled={reassess.isPending}>
                  Reassess
                </button>
              )}
              {!a.certification_requested && LIFECYCLE_UI[a.lifecycle_state]?.requestCertification && (
                <button type="button" className="primary" onClick={() => requestCert.mutate()} disabled={requestCert.isPending}>
                  Request certification
                </button>
              )}
            </div>
          </div>
          {a.failure_reason && (
            <div className="alert error" role="alert">
              Failed: {a.failure_reason}
            </div>
          )}
          {(cancel.error || reassess.error || requestCert.error) && (
            <div className="alert error" role="alert">
              {String((cancel.error ?? reassess.error ?? requestCert.error as Error)?.message)}
            </div>
          )}
          <Tabs<Tab>
            tabs={[
              { id: "overview", label: "Overview" },
              { id: "criteria", label: "Criteria" },
              { id: "sources", label: "Sources and runs" },
              { id: "reviews", label: "Reviews" },
            ]}
            value={tab}
            onChange={setTab}
          />
          <QueryState isLoading={report.isLoading} error={report.error}>
            {r && tab === "overview" && (
              <div role="tabpanel" id="panel-overview" aria-labelledby="tab-overview" className="grid">
                <div className="card">
                  <ScoreDial score={r.result?.hai_score ?? null} />
                  <div className="row" style={{ justifyContent: "center", marginTop: "0.75rem" }}>
                    <Badge tone={toneForOutcome(r.result?.outcome_status)}>{r.result?.outcome_label ?? "No result yet"}</Badge>
                  </div>
                  {r.result && (
                    <div className="row small muted" style={{ justifyContent: "center", marginTop: "0.5rem" }}>
                      <span>Confidence {fmtNum(r.result.confidence_pct)}</span>
                      <span>Effectiveness {fmtNum(r.result.effectiveness)}</span>
                      {r.result.caps_applied.length > 0 && <span>Caps: {r.result.caps_applied.join(", ")}</span>}
                    </div>
                  )}
                  {r.result && r.result.gate_reasons.length > 0 && (
                    <ul className="small muted" style={{ marginTop: "0.75rem" }}>
                      {r.result.gate_reasons.map((g) => (
                        <li key={g}>{g}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="card">
                  <h2>Pillars</h2>
                  <PillarBars pillars={r.pillars} />
                </div>
                <div className="card" style={{ gridColumn: "1 / -1" }}>
                  <h2>Coverage</h2>
                  <CoverageStrip cells={r.criteria.map((c) => ({ code: c.code, name: c.name, coverage_state: c.coverage_state, level: c.level }))} onSelect={setTraceCode} />
                  <p className="muted small" style={{ marginTop: "0.5rem" }}>
                    {Object.entries(r.coverage_summary)
                      .filter(([, n]) => n > 0)
                      .map(([s, n]) => `${label("coverage_state", s)}: ${n}`)
                      .join(", ")}
                    . Select a cell to open its trace.
                  </p>
                </div>
                <div className="card" style={{ gridColumn: "1 / -1" }}>
                  <h2>Version pins</h2>
                  <div className="row small mono">
                    {Object.entries(a.versions).map(([k, v]) => (
                      <span key={k}>
                        {k} {v}
                      </span>
                    ))}
                    {r.snapshot && <span>snapshot {r.snapshot.sha256.slice(0, 12)}</span>}
                  </div>
                  {r.execution_notes.length > 0 && (
                    <>
                      <h3 style={{ marginTop: "1rem" }}>Execution notes</h3>
                      <ul className="small">
                        {r.execution_notes.map((n) => (
                          <li key={n.code}>
                            <strong>{n.code}</strong> {n.name}: {n.note}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  <p className="muted small">{r.drafts_notice}</p>
                </div>
              </div>
            )}
            {r && tab === "criteria" && (
              <div role="tabpanel" id="panel-criteria" aria-labelledby="tab-criteria" className="card table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Criterion</th>
                      <th>Level</th>
                      <th>Coverage</th>
                      <th>Confidence</th>
                      <th>Evidence</th>
                      <th>Trace</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.criteria.map((c) => (
                      <tr key={c.code}>
                        <td className="mono">{c.code}</td>
                        <td>
                          {c.name} {c.review_required && <Badge tone="warn">review</Badge>}
                          <div className="small muted">{c.coverage_wording}</div>
                        </td>
                        <td>{c.level ?? "n/a"}</td>
                        <td>{label("coverage_state", c.coverage_state)}</td>
                        <td>{c.confidence === null ? "n/a" : fmtNum(c.confidence)}</td>
                        <td>{c.evidence.filter((e) => e.admissibility === "admissible").length} admissible</td>
                        <td>
                          <button type="button" className="ghost" onClick={() => setTraceCode(c.code)} aria-label={`Open trace for ${c.code}`}>
                            Trace
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {r && tab === "sources" && (
              <div role="tabpanel" id="panel-sources" aria-labelledby="tab-sources" className="stack">
                <div className="card table-wrap">
                  <h2>Connector runs</h2>
                  <QueryState isLoading={runs.isLoading} error={runs.error}>
                    <table>
                      <thead>
                        <tr>
                          <th>Connector</th>
                          <th>Outcome</th>
                          <th>Items</th>
                          <th>Error</th>
                          <th>Notes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(runs.data?.items ?? []).map((run) => (
                          <tr key={run.id}>
                            <td>{connectorLabel(run.code)}</td>
                            <td>
                              <Badge tone={run.outcome === "succeeded" ? "ok" : "bad"}>{run.outcome_label}</Badge>
                            </td>
                            <td>{run.items_returned}</td>
                            <td className="mono small">{run.error_code ?? ""}</td>
                            <td className="small muted">{run.notes ?? ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </QueryState>
                </div>
                <div className="card table-wrap">
                  <h2>Sources collected ({r.sources.length})</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>Title</th>
                        <th>Publisher</th>
                        <th>Published</th>
                        <th>Connector</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.sources.map((s) => (
                        <tr key={s.id}>
                          <td>
                            <a href={s.canonical_url} target="_blank" rel="noreferrer">
                              {s.title ?? s.canonical_url}
                            </a>
                          </td>
                          <td>
                            {s.publisher} <span className="muted small">({label("publisher_type", s.publisher_type)})</span>
                          </td>
                          <td>{s.published_at ? fmtDate(s.published_at) : "undated"}</td>
                          <td>{connectorLabel(s.connector)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            {r && tab === "reviews" && (
              <div role="tabpanel" id="panel-reviews" aria-labelledby="tab-reviews" className="stack">
                <div className="card">
                  <h2>Review tasks</h2>
                  <QueryState isLoading={tasks.isLoading} error={tasks.error}>
                    {(tasks.data?.items.length ?? 0) === 0 ? (
                      <p className="muted">No review tasks for this assessment.</p>
                    ) : (
                      <ul>
                        {tasks.data?.items.map((t) => (
                          <li key={t.id}>
                            <Badge tone={t.status === "closed" ? "ok" : "warn"}>{t.status}</Badge> {label("review_subject_type", t.subject_type)}: {t.reason}
                            {t.status !== "closed" && (
                              <>
                                {" "}
                                <Link to="/reviews">open in queue</Link>
                              </>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </QueryState>
                </div>
                {reviewer && r.result && <SignCertification assessmentId={id} gateReasons={r.result.gate_reasons} onDone={invalidate} />}
              </div>
            )}
          </QueryState>
          <TraceDrawer assessmentId={id} criterionCode={traceCode} onClose={() => setTraceCode(null)} />
        </div>
      )}
    </QueryState>
  );
}

function SignCertification({ assessmentId, gateReasons, onDone }: { assessmentId: string; gateReasons: string[]; onDone: () => void }) {
  const [decision, setDecision] = useState<"certified" | "not_certified">(gateReasons.length ? "not_certified" : "certified");
  const [reason, setReason] = useState("");
  const sign = useMutation({ mutationFn: () => api.signCertification(assessmentId, { decision, reason }), onSuccess: onDone });
  const err = sign.error instanceof ApiRequestError ? sign.error : null;
  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        sign.mutate();
      }}
    >
      <h2>Certification decision</h2>
      <p className="muted small">Only a named reviewer can sign. A certified decision needs every gate to pass{gateReasons.length ? `; currently: ${gateReasons.join("; ")}` : ""}.</p>
      <div className="field">
        <label htmlFor="decision">Decision</label>
        <select id="decision" value={decision} onChange={(e) => setDecision(e.target.value as "certified" | "not_certified")}>
          <option value="certified">Certified</option>
          <option value="not_certified">Not certified</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="sign-reason">Reason (required)</label>
        <textarea id="sign-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} aria-invalid={!!err} />
      </div>
      {err && (
        <div className="alert error" role="alert">
          {err.message}
        </div>
      )}
      {sign.data && (
        <div className="alert info" role="status">
          Signed: {String(sign.data["decision"])} {sign.data["certificate_number"] ? `(${String(sign.data["certificate_number"])})` : ""}
        </div>
      )}
      <button type="submit" className="primary" disabled={sign.isPending || reason.trim().length < 3}>
        Sign
      </button>
    </form>
  );
}
