import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../lib/api";
import { fmtDate, label } from "../lib/format";
import { Badge, QueryState } from "./widgets";

export function TraceDrawer({ assessmentId, criterionCode, onClose }: { assessmentId: string; criterionCode: string | null; onClose: () => void }) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const isOpen = !!criterionCode;
  const q = useQuery({
    queryKey: ["trace", assessmentId, criterionCode],
    queryFn: () => api.getCriterionTrace(assessmentId, criterionCode as string),
    enabled: !!criterionCode,
  });
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!isOpen) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const drawer = drawerRef.current;
      if (!drawer) return;
      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
        .filter((element) => !element.closest('[hidden], [aria-hidden="true"]'));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) {
        e.preventDefault();
        drawer.focus();
      } else if (e.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, [isOpen]);
  if (!criterionCode) return null;
  const c = q.data?.criteria[0];
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="trace-title" ref={drawerRef} tabIndex={-1}>
        <header>
          <div className="drawer-heading">
            <span className="eyebrow">Evidence & decision trail</span>
            <h2 id="trace-title">
              Trace: {criterionCode} {c ? c.criterion_name : ""}
            </h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close trace" ref={closeRef}>
            Close
          </button>
        </header>
        <QueryState isLoading={q.isLoading} error={q.error}>
          {c && (
            <div className="stack">
              <div className="row">
                <Badge tone="red">Level {c.level ?? "n/a"}</Badge>
                <Badge>{label("coverage_state", c.coverage_state)}</Badge>
                <Badge>Confidence {c.confidence.toFixed(1)}</Badge>
              </div>
              {c.finding && (
                <div className="card">
                  <h3>Proposal ({c.finding.model_id})</h3>
                  <p className="small">
                    Proposed level {c.finding.proposed_level}, uncertainty {c.finding.uncertainty.toFixed(2)}. {c.finding.reasoning_summary}
                  </p>
                  <p className="muted small">Advisory only. The rules below decided.</p>
                </div>
              )}
              <div className="card">
                <h3>Rules, in order</h3>
                <ol className="rule-trace">
                  {c.rules.map((r, i) => (
                    <li key={`${r.rule}-${i}`}>
                      <code>{r.rule}</code>: {r.note}
                      {String(r.before["level"]) !== String(r.after["level"]) && (
                        <span className="muted">
                          {" "}
                          (level {String(r.before["level"] ?? "none")} to {String(r.after["level"] ?? "none")})
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
              <div className="card">
                <h3>Evidence ({c.evidence.length})</h3>
                {c.evidence.length === 0 && <p className="muted">No links name this criterion.</p>}
                {c.evidence.map((e) => (
                  <div key={e.link_id} style={{ marginBottom: "0.9rem" }}>
                    <div className="row small">
                      <Badge tone={e.polarity === "supports" ? "ok" : e.polarity === "contradicts" ? "bad" : "info"}>{label("polarity", e.polarity)}</Badge>
                      <Badge tone={e.admissibility === "admissible" ? "ok" : "warn"}>{label("admissibility", e.admissibility)}</Badge>
                      <Badge>{label("maturity_rung", e.maturity_rung)}</Badge>
                      <Badge>{label("independence", e.independence)}</Badge>
                      {e.cited_by_finding && <Badge tone="red">Cited</Badge>}
                    </div>
                    <blockquote className="quote">{e.quote}</blockquote>
                    <div className="small muted">
                      {e.publisher_name ?? label("publisher_type", e.publisher_type)}
                      {e.published_at ? `, ${fmtDate(e.published_at)}` : ", undated"}
                      {e.section_heading ? `, section "${e.section_heading}"` : ""} {e.canonical_url && (
                        <a href={e.canonical_url} target="_blank" rel="noreferrer">
                          source
                        </a>
                      )}{" "}
                      <span className="mono">
                        chars {e.char_start}-{e.char_end}
                      </span>
                      {e.admissibility_reason ? ` (${e.admissibility_reason})` : ""}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </QueryState>
      </aside>
    </>
  );
}
