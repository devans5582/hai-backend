import { LABELS } from "../generated/ontology";

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

export function toneForOutcome(status: string | null | undefined): "ok" | "warn" | "bad" | "info" | "red" {
  switch (status) {
    case "hai_certified":
      return "ok";
    case "certification_not_yet_achieved":
      return "info";
    case "confidence_too_low":
    case "governance_baseline":
      return "warn";
    case "insufficient_evidence":
    case "access_limited":
      return "bad";
    default:
      return "info";
  }
}

export function toneForLifecycle(state: string): "ok" | "warn" | "bad" | "info" | "red" {
  switch (state) {
    case "completed":
      return "ok";
    case "completed_unverified":
      return "info";
    case "awaiting_review":
      return "warn";
    case "failed":
    case "cancelled":
      return "bad";
    default:
      return "red";
  }
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "";
}
