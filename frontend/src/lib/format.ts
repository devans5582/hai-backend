import { ATTRIBUTES, LABELS, type LifecycleState, type MaturityRung, type MaturityStatus, type OutcomeStatus } from "../generated/ontology";

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

/** How the console groups lifecycle states on the dashboard. Keys are checked against the generated union. */
export const LIFECYCLE_GROUP: Record<LifecycleState, { inProgress: boolean; completed: boolean; attention: boolean; awaitingHuman: boolean }> = {
  queued: { inProgress: true, completed: false, attention: false, awaitingHuman: false },
  acquiring: { inProgress: true, completed: false, attention: false, awaitingHuman: false },
  evaluating: { inProgress: true, completed: false, attention: false, awaitingHuman: false },
  awaiting_review: { inProgress: true, completed: false, attention: true, awaitingHuman: true },
  completed_unverified: { inProgress: false, completed: true, attention: false, awaitingHuman: false },
  completed: { inProgress: false, completed: true, attention: false, awaitingHuman: false },
  failed: { inProgress: false, completed: false, attention: true, awaitingHuman: false },
  cancelled: { inProgress: false, completed: false, attention: false, awaitingHuman: false },
};

export function lifecycleGroup(state: LifecycleState | string) {
  return LIFECYCLE_GROUP[state as LifecycleState] ?? { inProgress: false, completed: false, attention: false, awaitingHuman: false };
}

export function isTerminal(state: LifecycleState): boolean {
  return Boolean(ATTRIBUTES["lifecycle_state"]?.[state]?.["terminal"]);
}

const STATUS_TONE: Record<MaturityStatus, Tone> = {
  needs_attention: "bad",
  developing: "warn",
  progressing: "info",
  strong: "ok",
};

// How far up the ladder a piece of evidence climbs, as a badge tone. Keys are the generated union.
const RUNG_TONE: Record<MaturityRung, Tone> = {
  none: "bad",
  stated_commitment: "warn",
  specified_control: "warn",
  documented_execution: "info",
  independently_verified: "ok",
};

export function toneForRung(rung: MaturityRung | string | null | undefined): Tone {
  return (rung && RUNG_TONE[rung as MaturityRung]) || "info";
}

export function toneForStatus(status: MaturityStatus | string | null | undefined): Tone {
  return (status && STATUS_TONE[status as MaturityStatus]) || "info";
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
