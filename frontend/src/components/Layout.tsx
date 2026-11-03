import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { METHODOLOGY_VERSION, ONTOLOGY_VERSION } from "../generated/ontology";
import { applyTheme, readTheme, useAuth, type Theme } from "../lib/auth";
import { Icon, type IconName } from "./Icon";

const NAV: { to: string; label: string; icon: IconName; section: string }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard", section: "Workspace" },
  { to: "/assessments/new", label: "New assessment", icon: "plus", section: "Workspace" },
  { to: "/reviews", label: "Review queue", icon: "reviews", section: "Workspace" },
  { to: "/organizations", label: "Organizations", icon: "building", section: "Workspace" },
  { to: "/ontology", label: "Ontology", icon: "layers", section: "Resources" },
  { to: "/verify", label: "Verify certificate", icon: "shield", section: "Resources" },
];

export function Layout() {
  const { reviewer, apiKey, claims } = useAuth();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => {
    applyTheme(theme);
    const preference = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () => applyTheme(theme);
    if (theme === "system") preference?.addEventListener?.("change", update);
    return () => preference?.removeEventListener?.("change", update);
  }, [theme]);
  useEffect(() => { setMenuOpen(false); }, [pathname]);
  const who = reviewer ? claims?.name ?? claims?.sub ?? "Reviewer" : apiKey ? "API key connected" : "Guest workspace";
  const current = NAV.find((n) => n.to === pathname)?.label ?? (pathname.startsWith("/assessments/") ? "Assessment details" : pathname.startsWith("/organizations/") ? "Organization details" : pathname === "/settings" ? "Settings" : "Workspace");
  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className={`sidebar ${menuOpen ? "is-open" : ""}`}>
        <div className="sidebar-brand">
          <NavLink to="/" className="wordmark" aria-label="HAI Score console home">
            <span className="brand-symbol"><Icon name="activity" /></span>
            <span>HAI Score<span className="brand-caption">by humaital</span></span>
          </NavLink>
          <button className="mobile-menu icon-button" type="button" aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen} aria-controls="sidebar-content" onClick={() => setMenuOpen(!menuOpen)}><Icon name={menuOpen ? "x" : "menu"} /></button>
        </div>
        <div className="sidebar-content" id="sidebar-content" onKeyDown={(e) => { if (e.key === "Escape") { setMenuOpen(false); document.querySelector<HTMLButtonElement>(".mobile-menu")?.focus(); } }}>
          <div className="workspace-switch"><span className="workspace-avatar">H</span><div><strong>Governance workspace</strong><span>HAI Score Console</span></div><Icon name="lock" /></div>
          <nav className="nav" aria-label="Primary">
            {["Workspace", "Resources"].map((section) => <div className="nav-group" key={section}><span className="nav-caption">{section}</span>{NAV.filter((n) => n.section === section).map((n) => <NavLink key={n.to} to={n.to} end={n.to === "/"}><Icon name={n.icon} /><span>{n.label}</span><Icon className="nav-arrow" name="chevron-right" /></NavLink>)}</div>)}
          </nav>
          <div className="sidebar-bottom">
            <div className="sidebar-note"><Icon name="shield" /><strong>Evidence behind every score.</strong><p>Six pillars. Twenty criteria.<br />One clearer picture.</p><Link to="/ontology">Explore the framework <Icon name="arrow-right" /></Link></div>
            <NavLink className="settings-link" to="/settings"><Icon name="settings" />Settings<Icon name="chevron-right" /></NavLink>
            <div className="theme-control"><Icon name="sun" /><label className="sr-only" htmlFor="theme">Theme</label><select id="theme" value={theme} onChange={(e) => setTheme(e.target.value as Theme)}><option value="system">System theme</option><option value="light">Light theme</option><option value="dark">Dark theme</option></select></div>
          </div>
        </div>
      </aside>
      <div className="workspace-body">
        <header className="topbar">
          <div className="breadcrumb"><span>Console</span><Icon name="chevron-right" /><strong>{current}</strong></div>
          <div className="topbar-actions"><Link to="/verify" className="public-link"><Icon name="shield" />Public verification</Link><span className="topbar-divider" /><Link to="/settings" className="user-menu"><span className={`user-avatar ${reviewer || apiKey ? "connected" : ""}`}>{reviewer ? (who[0] ?? "R").toUpperCase() : <Icon name="key" />}</span><span><strong>{who}</strong><small>{reviewer ? claims?.role : apiKey ? "Ready to assess" : "Connect to get started"}</small></span><Icon name="chevron-down" /></Link></div>
        </header>
        <main id="main" className="main" tabIndex={-1}><Outlet /></main>
        <footer className="app-footer"><span><span className="footer-dot" />Human Alignment Index</span><span>Ontology {ONTOLOGY_VERSION}<span className="footer-separator">/</span>Methodology {METHODOLOGY_VERSION}</span></footer>
      </div>
    </div>
  );
}
