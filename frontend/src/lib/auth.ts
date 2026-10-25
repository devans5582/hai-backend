// Credentials live in localStorage only; the browser never computes a score or a status.
import { useCallback, useEffect, useState } from "react";

const KEY_API = "hai.apiKey";
const KEY_TOKEN = "hai.reviewerToken";
const KEY_THEME = "hai.theme";

export type Theme = "light" | "dark" | "system";

export interface Credentials {
  apiKey: string | null;
  reviewerToken: string | null;
}

export function readCredentials(): Credentials {
  return { apiKey: localStorage.getItem(KEY_API), reviewerToken: localStorage.getItem(KEY_TOKEN) };
}

export function authHeaders(): Record<string, string> {
  const { apiKey, reviewerToken } = readCredentials();
  if (reviewerToken) return { Authorization: `Bearer ${reviewerToken}` };
  if (apiKey) return { "X-API-Key": apiKey };
  return {};
}

export interface TokenClaims {
  sub: string;
  name?: string;
  role?: "reviewer" | "admin";
  scopes?: string[];
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
  const claims = decodeToken(readCredentials().reviewerToken);
  return claims?.role === "reviewer" || claims?.role === "admin";
}

const listeners = new Set<() => void>();
function notify() {
  listeners.forEach((l) => l());
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
  const save = useCallback((next: Partial<Credentials>) => {
    if (next.apiKey !== undefined) {
      if (next.apiKey) localStorage.setItem(KEY_API, next.apiKey);
      else localStorage.removeItem(KEY_API);
    }
    if (next.reviewerToken !== undefined) {
      if (next.reviewerToken) localStorage.setItem(KEY_TOKEN, next.reviewerToken);
      else localStorage.removeItem(KEY_TOKEN);
    }
    notify();
  }, []);
  const claims = decodeToken(creds.reviewerToken);
  return { ...creds, claims, reviewer: claims?.role === "reviewer" || claims?.role === "admin", save };
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
