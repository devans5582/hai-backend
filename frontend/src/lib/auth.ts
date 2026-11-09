// Credentials live in localStorage only; the browser never computes a score or a status.
// Three ways in: a console session (email and password), an admin-minted reviewer token, or
// a partner API key. The session wins when present; the others remain for partners and operators.
import { useCallback, useEffect, useState } from "react";

const KEY_SESSION = "hai.session";
const KEY_API = "hai.apiKey";
const KEY_TOKEN = "hai.reviewerToken";
const KEY_THEME = "hai.theme";

export type Theme = "light" | "dark" | "system";

export interface Credentials {
  session: string | null;
  apiKey: string | null;
  reviewerToken: string | null;
}

export type AuthMode = "session" | "credential" | "none";

export function readCredentials(): Credentials {
  return {
    session: localStorage.getItem(KEY_SESSION),
    apiKey: localStorage.getItem(KEY_API),
    reviewerToken: localStorage.getItem(KEY_TOKEN),
  };
}

export function authMode(creds: Credentials = readCredentials()): AuthMode {
  if (creds.session) return "session";
  if (creds.apiKey || creds.reviewerToken) return "credential";
  return "none";
}

export function authHeaders(): Record<string, string> {
  const { session, apiKey, reviewerToken } = readCredentials();
  if (session) return { Authorization: `Bearer ${session}` };
  if (reviewerToken) return { Authorization: `Bearer ${reviewerToken}` };
  if (apiKey) return { "X-API-Key": apiKey };
  return {};
}

export interface TokenClaims {
  sub: string;
  name?: string;
  email?: string;
  role?: "reviewer" | "admin" | "user";
  account_role?: string;
  account?: string;
  account_kind?: "platform" | "organization";
  scopes?: string[];
  sid?: string;
  exp?: number;
}

export function decodeToken(token: string | null): TokenClaims | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const json = atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as TokenClaims;
  } catch {
    return null;
  }
}

export function isReviewer(): boolean {
  const creds = readCredentials();
  const claims = decodeToken(creds.session ?? creds.reviewerToken);
  return claims?.role === "reviewer" || claims?.role === "admin";
}

const listeners = new Set<() => void>();
function notify() {
  listeners.forEach((l) => l());
}

function write(key: string, value: string | null | undefined) {
  if (value === undefined) return;
  if (value) localStorage.setItem(key, value);
  else localStorage.removeItem(key);
}

export function saveCredentials(next: Partial<Credentials>) {
  write(KEY_SESSION, next.session);
  write(KEY_API, next.apiKey);
  write(KEY_TOKEN, next.reviewerToken);
  notify();
}

/** Called by the API client on a 401 for a session: the session is gone server-side. */
export function dropSession() {
  if (localStorage.getItem(KEY_SESSION)) {
    localStorage.removeItem(KEY_SESSION);
    notify();
  }
}

export function clearAllCredentials() {
  saveCredentials({ session: null, apiKey: null, reviewerToken: null });
}

export function useAuth() {
  const [creds, setCreds] = useState<Credentials>(readCredentials);
  useEffect(() => {
    const l = () => setCreds(readCredentials());
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);
  const save = useCallback((next: Partial<Credentials>) => saveCredentials(next), []);
  const claims = decodeToken(creds.session ?? creds.reviewerToken);
  const mode = authMode(creds);
  return {
    ...creds,
    claims,
    mode,
    authenticated: mode !== "none",
    reviewer: claims?.role === "reviewer" || claims?.role === "admin",
    save,
  };
}

export function readTheme(): Theme {
  const t = localStorage.getItem(KEY_THEME);
  return t === "light" || t === "dark" ? t : "system";
}

export function applyTheme(theme: Theme) {
  localStorage.setItem(KEY_THEME, theme);
  const dark = theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}
