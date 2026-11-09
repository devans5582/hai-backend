import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { METHODOLOGY_VERSION, ONTOLOGY_VERSION } from "../generated/ontology";
import { api } from "../lib/api";
import { applyTheme, clearAllCredentials, readTheme, useAuth, type Theme } from "../lib/auth";
import { useMe, type Capabilities } from "../lib/me";
import { roleLabel } from "../lib/roles";
import { BrandLogo } from "./BrandLogo";
import { Icon, type IconName } from "./Icon";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  section: string;
  show?: (c: Capabilities) => boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: "dashboard", section: "Workspace" },
  { to: "/assessments/new", label: "New assessment", icon: "plus", section: "Workspace", show: (c) => c.startAssessments },
  { to: "/reviews", label: "Review queue", icon: "reviews", section: "Workspace", show: (c) => c.reviewQueue },
  { to: "/organizations", label: "Organizations", icon: "building", section: "Workspace" },
  { to: "/team", label: "Team and access", icon: "users", section: "Administration", show: (c) => c.manageTeam },
  { to: "/ontology", label: "Ontology", icon: "layers", section: "Resources" },
  { to: "/verify", label: "Verify certificate", icon: "shield", section: "Resources" },
];

const SECTIONS = ["Workspace", "Administration", "Resources"];

export function Layout() {
  const { reviewer, apiKey, claims, mode, session } = useAuth();
  const { me, capabilities } = useMe();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useEffect(() => {
    applyTheme(theme);
    const preference = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () => applyTheme(theme);
    if (theme === "system") preference?.addEventListener?.("change", update);
    return () => preference?.removeEventListener?.("change", update);
  }, [theme]);
  useEffect(() => { setMenuOpen(false); setUserMenuOpen(false); }, [pathname]);
  useEffect(() => {
    if (!userMenuOpen) return;
    const onClick = (e: MouseEvent) => { if (!userMenuRef.current?.contains(e.target as Node)) setUserMenuOpen(false); };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [userMenuOpen]);

  const signOut = async () => {
    if (session) {
      try { await api.logout(); } catch { /* the session is dropped locally regardless */ }
    }
    clearAllCredentials();
    queryClient.clear();
    navigate("/login", { replace: true });
  };

  // The API decides who the user is; until it answers, fall back to what the token says.
  const displayName = me?.user?.name ?? me?.principal.name ?? claims?.name ?? claims?.sub ?? (apiKey ? "API key connected" : "Connected");
  const roleText = me?.user ? roleLabel(me.user.role, me.roles.roles) : mode === "credential" ? (reviewer ? roleLabel(claims?.role === "admin" ? "admin" : "reviewer") : "API key access") : "";
  const accountName = me?.account?.name ?? (mode === "credential" ? "Partner access" : "Workspace");
  const accountKind = me?.account?.kind === "organization" ? "Participating organization" : me?.account?.kind === "platform" ? "Governance workspace" : "HAI Score Console";
  const visibleNav = NAV.filter((n) => !n.show || n.show(capabilities) || (!me && mode === "credential" && n.to !== "/team"));
  const current = NAV.find((n) => n.to === pathname)?.label ?? (pathname.startsWith("/assessments/") ? "Assessment details" : pathname.startsWith("/organizations/") ? "Organization details" : pathname === "/settings" ? "Settings" : "Workspace");
  const initial = (displayName[0] ?? "H").toUpperCase();
  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className={`sidebar ${menuOpen ? "is-open" : ""}`}>
        <div className="sidebar-brand">
          <NavLink to="/" className="wordmark" aria-label="HAI Score console home">
            <BrandLogo height={18} plate />
            <span className="brand-product">HAI Score<span className="brand-caption">Console</span></span>
          </NavLink>
          <button className="mobile-menu icon-button" type="button" aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen} aria-controls="sidebar-content" onClick={() => setMenuOpen(!menuOpen)}><Icon name={menuOpen ? "x" : "menu"} /></button>
        </div>
        <div className="sidebar-content" id="sidebar-content" onKeyDown={(e) => { if (e.key === "Escape") { setMenuOpen(false); document.querySelector<HTMLButtonElement>(".mobile-menu")?.focus(); } }}>
          <div className="workspace-switch"><span className="workspace-avatar">{(accountName[0] ?? "H").toUpperCase()}</span><div><strong>{accountName}</strong><span>{accountKind}</span></div><Icon name={me?.account?.kind === "organization" ? "building" : "lock"} /></div>
          <nav className="nav" aria-label="Primary">
            {SECTIONS.filter((section) => visibleNav.some((n) => n.section === section)).map((section) => <div className="nav-group" key={section}><span className="nav-caption">{section}</span>{visibleNav.filter((n) => n.section === section).map((n) => <NavLink key={n.to} to={n.to} end={n.to === "/"}><Icon name={n.icon} /><span>{n.label}</span><Icon className="nav-arrow" name="chevron-right" /></NavLink>)}</div>)}
          </nav>
          <div className="sidebar-bottom">
            {capabilities.organizationAccount ? (
              <div className="sidebar-note"><Icon name="building" /><strong>Your organization's reports.</strong><p>Every score traces back<br />to the evidence behind it.</p><Link to="/ontology">How scoring works <Icon name="arrow-right" /></Link></div>
            ) : (
              <div className="sidebar-note"><Icon name="shield" /><strong>Evidence behind every score.</strong><p>Six pillars. Twenty criteria.<br />One clearer picture.</p><Link to="/ontology">Explore the framework <Icon name="arrow-right" /></Link></div>
            )}
            <NavLink className="settings-link" to="/settings"><Icon name="settings" />Settings<Icon name="chevron-right" /></NavLink>
            <div className="theme-control"><Icon name="sun" /><label className="sr-only" htmlFor="theme">Theme</label><select id="theme" value={theme} onChange={(e) => setTheme(e.target.value as Theme)}><option value="system">System theme</option><option value="light">Light theme</option><option value="dark">Dark theme</option></select></div>
          </div>
        </div>
      </aside>
      <div className="workspace-body">
        <header className="topbar">
          <div className="breadcrumb"><span>Console</span><Icon name="chevron-right" /><strong>{current}</strong></div>
          <div className="topbar-actions">
            <Link to="/verify" className="public-link"><Icon name="shield" />Public verification</Link>
            <span className="topbar-divider" />
            <div className="user-menu-wrap" ref={userMenuRef}>
              <button type="button" className="user-menu" aria-haspopup="menu" aria-expanded={userMenuOpen} aria-label="Account menu" onClick={() => setUserMenuOpen(!userMenuOpen)}>
                <span className={`user-avatar ${mode !== "none" ? "connected" : ""}`}>{mode === "credential" && !reviewer ? <Icon name="key" /> : initial}</span>
                <span><strong>{displayName}</strong><small>{roleText || "Connected"}</small></span>
                <Icon name="chevron-down" />
              </button>
              {userMenuOpen && (
                <div className="user-popover" role="menu" aria-label="Account">
                  <div className="user-popover-head"><strong>{displayName}</strong>{me?.user?.email && <span>{me.user.email}</span>}{roleText && <span className="badge red">{roleText}</span>}</div>
                  <Link role="menuitem" to="/settings" className="user-popover-item"><Icon name="user" />Profile and settings</Link>
                  <Link role="menuitem" to="/settings?tab=access" className="user-popover-item"><Icon name="key" />API access</Link>
                  {capabilities.manageTeam && <Link role="menuitem" to="/team" className="user-popover-item"><Icon name="users" />Team and access</Link>}
                  <button role="menuitem" type="button" className="user-popover-item" onClick={() => void signOut()}><Icon name="log-out" />Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main id="main" className="main" tabIndex={-1}><Outlet /></main>
        <footer className="app-footer"><span><span className="footer-dot" />Human Alignment Index</span><span>Ontology {ONTOLOGY_VERSION}<span className="footer-separator">/</span>Methodology {METHODOLOGY_VERSION}</span></footer>
      </div>
    </div>
  );
}
