import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { TraceDrawer } from "../components/TraceDrawer";
import { Badge, CoverageStrip, PillarBars, QueryState, ScoreDial, Tabs } from "../components/widgets";
import { api, ApiRequestError, type Assessment } from "../lib/api";
import { useAuth } from "../lib/auth";
import { connectorLabel } from "../lib/connectors";
import { fmtDate, fmtDateTime, fmtNum, label, LIFECYCLE_UI, lifecycleGroup, toneForLifecycle, toneForOutcome, toneForRung, toneForStatus } from "../lib/format";

type Tab = "overview" | "criteria" | "sources" | "reviews";

const PROCESSING_HELP: Partial<Record<Assessment["lifecycle_state"], string>> = {
  queued: "Your assessment is in the queue. Evidence collection will begin when a worker is available.",
  acquiring: "We’re collecting public evidence for this organization. Results will appear as the assessment progresses.",
  evaluating: "Evidence is being evaluated against the assessment criteria. The rules engine will determine the result.",
  awaiting_review: "This assessment needs a reviewer’s attention before it can be finalized. Open the Reviews tab to see the outstanding tasks.",
};

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
  const history = useQuery({ queryKey: ["org-history", assessment.data?.org_id], queryFn: () => api.organizationHistory(assessment.data!.org_id), enabled: !!assessment.data });
  const version = history.data?.items.find((v) => v.assessment.id === id) ?? null;
  const invalidate = () => qc.invalidateQueries();
  const cancel = useMutation({ mutationFn: () => api.cancelAssessment(id), onSuccess: invalidate });
  const reassess = useMutation({ mutationFn: () => api.reassess(id), onSuccess: invalidate });
  const requestCert = useMutation({ mutationFn: () => api.requestCertification(id), onSuccess: invalidate });
  const a = assessment.data;
  const r = report.data;
  return (
    <QueryState isLoading={assessment.isLoading} error={assessment.error}>
      {a && (
        <div className="stack assessment-detail">
          <Link className="back-link" to="/"><Icon name="arrow-left" /> Back to dashboard</Link>
          <div className="page-head">
            <div>
              <span className="eyebrow">{version ? `Assessment version ${version.version} of ${history.data?.total ?? version.version}` : "Assessment overview"}</span>
              <h1>{r?.organization.name ?? a.submitted_domain}</h1>
              <div className="row small muted assessment-meta">
                <span className="mono">{a.submitted_domain}</span>
                <Badge tone={toneForLifecycle(a.lifecycle_state)}>{a.lifecycle_label}</Badge>
                <span>
                  {label("stage_band", a.stage_band)} / {label("size_band", a.size_band)}
                </span>
                <span>Created {fmtDateTime(a.created_at)}</span>
                <Link to={`/organizations/${a.org_id}`}>All versions</Link>
              </div>
            </div>
            <div className="actions">
              {LIFECYCLE_UI[a.lifecycle_state]?.cancel && (
                <button type="button" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                  {cancel.isPending ? "Cancelling…" : "Cancel"}
                </button>
              )}
              {LIFECYCLE_UI[a.lifecycle_state]?.reassess && (
                <button type="button" onClick={() => reassess.mutate()} disabled={reassess.isPending}>
                  <Icon name="refresh" /> {reassess.isPending ? "Starting…" : "Reassess"}
                </button>
              )}
              {!a.certification_requested && LIFECYCLE_UI[a.lifecycle_state]?.requestCertification && (
                <button type="button" className="primary" onClick={() => requestCert.mutate()} disabled={requestCert.isPending}>
                  <Icon name="shield" /> {requestCert.isPending ? "Requesting…" : "Request certification"}
                </button>
              )}
            </div>
          </div>
          {PROCESSING_HELP[a.lifecycle_state] && (
            <div className="alert info assessment-progress" role="status">
              <Icon name={lifecycleGroup(a.lifecycle_state).awaitingHuman ? "reviews" : "clock"} />
              <div>
                <strong>{a.lifecycle_label}</strong>
                <p>{PROCESSING_HELP[a.lifecycle_state]}</p>
                {LIFECYCLE_UI[a.lifecycle_state]?.polling && <span className="small muted">This page updates automatically. You can return to the dashboard while it runs.</span>}
              </div>
            </div>
          )}
          {version && !version.is_latest && history.data?.latest_id && (
            <div className="alert info" role="status">
              This is version {version.version}; a newer assessment of this organization exists. <Link to={`/assessments/${history.data.latest_id}`}>Open the latest version</Link>.
            </div>
          )}
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
              <div role="tabpanel" id="panel-overview" aria-labelledby="tab-overview" className="grid assessment-overview">
                <div className="card score-card">
                  <h2>Assessment result</h2>
                  <p className="muted small">Human Alignment Index · out of 100</p>
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
                  <p className="muted small">Performance across the governance pillars.</p>
                  <PillarBars pillars={r.pillars} />
                  {r.pillars.length === 0 && <p className="muted small">Pillar scores will appear when evaluation is complete.</p>}
                  {r.pillars.some((p) => p.status) && (
                    <ul className="status-list" aria-label="Pillar status">
                      {r.pillars.filter((p) => p.status).map((p) => (
                        <li key={p.code}><span>{p.name}</span><Badge tone={toneForStatus(p.status)}>{p.status_label}</Badge><small className="muted">{p.status_wording}</small></li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="card">
                  <h2>Evidence basis</h2>
                  <p className="muted small">What the admissible supporting evidence is: statements, documented controls, test results or independent verification. Counts of stored links; the score reads the ladder.</p>
                  <EvidenceBasis basis={r.evidence_basis?.by_rung ?? {}} labels={r.evidence_basis?.labels ?? {}} />
                  <dl className="strength-list">
                    {Object.entries(r.evidence_strength ?? {}).map(([code, st]) => (
                      <div key={code}><dt>{st.label}</dt><dd><Badge tone={st.strength === "None" ? "bad" : st.strength === "Limited" ? "warn" : st.strength === "Emerging" ? "info" : "ok"}>{st.strength}</Badge> <span className="small muted">{st.criteria_with_evidence} of {r.evidence_basis?.criteria_counted ?? 0} criteria</span></dd></div>
                    ))}
                  </dl>
                  {r.confidence_methodology && <p className="small muted">Confidence follows the published model: {Object.entries(r.confidence_methodology.weights).map(([k, w]) => `${k.replaceAll("_", " ")} ${Math.round(w * 100)}%`).join(", ")}.</p>}
                </div>
                <div className="card" style={{ gridColumn: "1 / -1" }}>
                  <h2>Focus areas</h2>
                  <p className="muted small">The seven areas the methodology looks at beyond documented policy. Each shows the criteria it bears on and how far the tagged evidence climbs the ladder. Coverage is reported; it never changes a weight.</p>
                  <div className="focus-grid">
                    {(r.focus_areas ?? []).map((fa) => (
                      <div className="focus-card" key={fa.code}>
                        <div className="focus-head"><strong>{fa.label}</strong>{fa.cross_cutting ? <Badge>Every criterion</Badge> : fa.best_rung_label ? <Badge tone={toneForRung(fa.best_rung)}>{fa.best_rung_label}</Badge> : <Badge tone="bad">No tagged evidence</Badge>}</div>
                        <p className="small muted">{fa.question}</p>
                        <p className="small">{fa.cross_cutting ? "Applied through the maturity ladder on every criterion." : `${fa.links} tagged link${fa.links === 1 ? "" : "s"} · ${fa.criteria.join(", ") || "no criteria mapped"}`}</p>
                      </div>
                    ))}
                  </div>
                  {r.verification && r.incident_response && r.impact_measures && (r.verification.controls.length > 0 || r.incident_response.length > 0 || r.impact_measures.total > 0) && (
                    <div className="row small muted" style={{ marginTop: "0.75rem" }}>
                      {r.verification.controls.length > 0 && <span>{r.verification.controls.length} control{r.verification.controls.length === 1 ? "" : "s"} on record, {r.verification.controls_with_unexercised_capabilities} with an unexercised stop capability</span>}
                      {r.incident_response.length > 0 && <span>{r.incident_response.filter((i) => i.correction_verified).length} of {r.incident_response.length} incident corrections independently verified</span>}
                      {r.impact_measures.total > 0 && <span>{r.impact_measures.demonstrated_benefit} of {r.impact_measures.total} impact measures demonstrate benefit</span>}
                    </div>
                  )}
                </div>
                <div className="card" style={{ gridColumn: "1 / -1" }}>
                  <h2>Coverage</h2>
                  <p className="muted small">Select a criterion to explore its evidence and the rules behind its result. Each tile shows the stored coverage state and level.</p>
                  <CoverageStrip cells={r.criteria.map((c) => ({ code: c.code, name: c.name, coverage_state: c.coverage_state, level: c.level }))} onSelect={setTraceCode} />
                  <p className="muted small" style={{ marginTop: "0.5rem" }}>
                    {Object.entries(r.coverage_summary)
                      .filter(([, n]) => n > 0)
                      .map(([s, n]) => `${label("coverage_state", s)}: ${n}`)
                      .join(", ")}
                  </p>
                </div>
                <details className="card version-details" style={{ gridColumn: "1 / -1" }}>
                  <summary>
                    <span>Assessment details</span>
                    <span className="muted small">Versions & execution notes</span>
                    <Icon name="chevron-down" />
                  </summary>
                  <div className="version-details-body">
                    <h3>Version pins</h3>
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
                </details>
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
                        {(runs.data?.items.length ?? 0) === 0 && <tr><td colSpan={5} className="table-empty muted">No connector runs yet. Runs will appear once evidence collection begins.</td></tr>}
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
                      {r.sources.length === 0 && <tr><td colSpan={4} className="table-empty muted">No sources have been collected for this assessment.</td></tr>}
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
        {sign.isPending ? "Signing…" : "Sign"}
      </button>
    </form>
  );
}

function EvidenceBasis({ basis, labels }: { basis: Record<string, number>; labels: Record<string, string> }) {
  const total = Object.values(basis).reduce((a, b) => a + b, 0);
  const order = Object.keys(labels);
  return (
    <div className="basis-bars" role="list" aria-label="Evidence by maturity rung">
      {order.map((rung) => {
        const n = basis[rung] ?? 0;
        const pct = total ? Math.round((n / total) * 100) : 0;
        return (
          <div className="basis-row" role="listitem" key={rung}>
            <span>{labels[rung]}</span>
            <div className="track" aria-hidden="true"><div className={`fill rung-${rung}`} style={{ width: `${pct}%` }} /></div>
            <span className="num" aria-label={`${labels[rung]}: ${n} links`}>{n}</span>
          </div>
        );
      })}
      {total === 0 && <p className="small muted">No admissible supporting evidence yet.</p>}
    </div>
  );
}
