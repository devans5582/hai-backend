import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { METHODOLOGY_VERSION, ONTOLOGY_VERSION } from "../generated/ontology";
import { applyTheme, readTheme, useAuth, type Theme } from "../lib/auth";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/assessments/new", label: "New assessment" },
  { to: "/reviews", label: "Reviews" },
  { to: "/organizations", label: "Organizations" },
  { to: "/ontology", label: "Ontology" },
  { to: "/verify", label: "Verify" },
  { to: "/settings", label: "Settings" },
];

export function Layout() {
  const { reviewer, apiKey, claims } = useAuth();
  const [theme, setTheme] = useState<Theme>(readTheme());
  useEffect(() => applyTheme(theme), [theme]);
  const who = reviewer ? `${claims?.name ?? claims?.sub} (${claims?.role})` : apiKey ? "API key" : "not signed in";
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <NavLink to="/" className="wordmark" aria-label="HAI Score console home">
          <span className="mark">HAI</span>
          <span>Score Console</span>
        </NavLink>
        <nav className="nav" aria-label="Primary">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="row small muted">
          <span aria-live="polite">{who}</span>
          <label className="sr-only" htmlFor="theme">
            Theme
          </label>
          <select id="theme" value={theme} onChange={(e) => setTheme(e.target.value as Theme)} style={{ width: "auto", padding: "0.3rem 0.5rem" }}>
            <option value="system">System</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
      </header>
      <main id="main" className="main">
        <Outlet />
      </main>
      <footer className="muted small" style={{ padding: "0.75rem 1rem", borderTop: "1px solid var(--border)" }}>
        Human Alignment Index. Ontology {ONTOLOGY_VERSION}, methodology {METHODOLOGY_VERSION}. Scores and statuses are shown exactly as the rules engine stored them.
      </footer>
    </div>
  );
}
