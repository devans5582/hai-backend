import { ATTRIBUTES, LABELS, type LifecycleState, type OutcomeStatus } from "../generated/ontology";

export function label(vocabulary: string, code: string | null | undefined): string {
  if (!code) return "";
  return LABELS[vocabulary]?.[code] ?? code;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtNum(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "n/a";
  return value.toFixed(digits);
}

export type Tone = "ok" | "warn" | "bad" | "info" | "red";

// Keys are checked against the generated unions: a renamed vocabulary value fails the typecheck.
const OUTCOME_TONE: Record<OutcomeStatus, Tone> = {
  hai_certified: "ok",
  certification_not_yet_achieved: "info",
  confidence_too_low: "warn",
  governance_baseline: "warn",
  insufficient_evidence: "bad",
  access_limited: "bad",
};

const LIFECYCLE_TONE: Record<LifecycleState, Tone> = {
  queued: "red",
  acquiring: "red",
  evaluating: "red",
  awaiting_review: "warn",
  completed_unverified: "info",
  completed: "ok",
  failed: "bad",
  cancelled: "bad",
};

/** What the console offers for an assessment in each lifecycle state. Terminal comes from the vocabulary. */
export const LIFECYCLE_UI: Record<LifecycleState, { polling: boolean; cancel: boolean; reassess: boolean; requestCertification: boolean }> = {
  queued: { polling: true, cancel: true, reassess: false, requestCertification: false },
  acquiring: { polling: true, cancel: true, reassess: false, requestCertification: false },
  evaluating: { polling: true, cancel: false, reassess: false, requestCertification: false },
  awaiting_review: { polling: false, cancel: false, reassess: false, requestCertification: false },
  completed_unverified: { polling: false, cancel: false, reassess: true, requestCertification: true },
  completed: { polling: false, cancel: false, reassess: true, requestCertification: false },
  failed: { polling: false, cancel: false, reassess: true, requestCertification: false },
  cancelled: { polling: false, cancel: false, reassess: false, requestCertification: false },
};

export function isTerminal(state: LifecycleState): boolean {
  return Boolean(ATTRIBUTES["lifecycle_state"]?.[state]?.["terminal"]);
}

export function toneForOutcome(status: OutcomeStatus | string | null | undefined): Tone {
  return (status && OUTCOME_TONE[status as OutcomeStatus]) || "info";
}

export function toneForLifecycle(state: LifecycleState | string): Tone {
  return LIFECYCLE_TONE[state as LifecycleState] ?? "info";
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "";
}
