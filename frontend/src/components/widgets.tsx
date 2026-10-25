import type { ReactNode } from "react";
import { COVERAGE_STATE_VALUES, LABELS, type CoverageState } from "../generated/ontology";
import type { ApiRequestError, PillarResult } from "../lib/api";
import { fmtNum } from "../lib/format";

export function Badge({ tone = "info", children }: { tone?: "ok" | "warn" | "bad" | "info" | "red"; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function ScoreDial({ score, label = "HAI Score", max = 100 }: { score: number | null; label?: string; max?: number }) {
  const r = 78;
  const c = 2 * Math.PI * r;
  const value = score ?? 0;
  const dash = (Math.max(0, Math.min(max, value)) / max) * c;
  const text = score === null ? "n/a" : fmtNum(score, 1);
  return (
    <div className="dial" role="img" aria-label={`${label}: ${text} out of ${max}`}>
      <svg viewBox="0 0 180 180" aria-hidden="true">
        <circle cx="90" cy="90" r={r} fill="none" stroke="var(--bg-3)" strokeWidth="14" />
        <circle cx="90" cy="90" r={r} fill="none" stroke="var(--hai-red)" strokeWidth="14" strokeLinecap="round" strokeDasharray={`${dash} ${c - dash}`} />
      </svg>
      <div className="center">
        <div className="score">{text}</div>
        <div className="label">{label}</div>
      </div>
    </div>
  );
}

export function PillarBars({ pillars }: { pillars: PillarResult[] | { code: string; name: string; score: number | null; confidence: number | null; criteria_counted: number; criteria_excluded: number }[] }) {
  return (
    <div className="bars" role="list" aria-label="Pillar scores">
      {pillars.map((p) => (
        <div className="bar" role="listitem" key={p.code}>
          <span title={p.code}>{p.name}</span>
          <div className="track" aria-hidden="true">
            <div className="fill" style={{ width: `${Math.max(0, Math.min(100, p.score ?? 0))}%` }} />
          </div>
          <span className="num" aria-label={`${p.name} score ${fmtNum(p.score)}`}>
            {p.score === null ? "n/a" : fmtNum(p.score, 0)}
          </span>
        </div>
      ))}
    </div>
  );
}

export interface CoverageCell {
  code: string;
  name: string;
  coverage_state: CoverageState | null;
  level: number | null;
}

export function CoverageStrip({ cells, onSelect }: { cells: CoverageCell[]; onSelect?: (code: string) => void }) {
  return (
    <div>
      <div className="strip" role="list" aria-label="Coverage by criterion">
        {cells.map((c) => {
          const state = c.coverage_state ?? "missing";
          const text = `${c.code} ${c.name}: ${LABELS["coverage_state"]?.[state] ?? state}${c.level ? `, level ${c.level}` : ""}`;
          return (
            <button key={c.code} type="button" className={`cell cov-${state}`} role="listitem" title={text} aria-label={text} onClick={() => onSelect?.(c.code)} />
          );
        })}
      </div>
      <div className="legend" aria-hidden="true">
        {COVERAGE_STATE_VALUES.map((s) => (
          <span key={s}>
            <span className={`swatch cov-${s}`} />
            {LABELS["coverage_state"]?.[s]}
          </span>
        ))}
      </div>
    </div>
  );
}

export function QueryState({ isLoading, error, children }: { isLoading: boolean; error: unknown; children: ReactNode }) {
  if (isLoading) return <p className="muted" aria-live="polite">Loading...</p>;
  if (error) {
    const e = error as Partial<ApiRequestError> & { message?: string };
    return (
      <div className="alert error" role="alert">
        {e.status === 401 ? "Sign in on the Settings page to continue. " : ""}
        {e.message ?? "Request failed"}
      </div>
    );
  }
  return <>{children}</>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" type="button" aria-selected={value === t.id} aria-controls={`panel-${t.id}`} id={`tab-${t.id}`} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ id, label, error, help, children }: { id: string; label: string; error?: string; help?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {help && !error && (
        <div className="help" id={`${id}-help`}>
          {help}
        </div>
      )}
      {error && (
        <div className="error" id={`${id}-error`} role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
