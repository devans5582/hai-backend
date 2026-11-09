import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { METHODOLOGY_VERSION, ONTOLOGY_VERSION, PILLARS } from "../generated/ontology";
import { applyTheme, readTheme, type Theme } from "../lib/auth";
import { BrandLogo } from "./BrandLogo";
import { Icon } from "./Icon";

/** The shell for pages that work without a sign-in: sign in, sign up, certificate verification. */
export function PublicLayout() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  return (
    <div className="auth-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className="auth-brand" aria-label="About HAI Score">
        <Link to="/login" className="wordmark" aria-label="HAI Score console">
          <BrandLogo height={26} plate />
          <span className="brand-product">HAI Score<span className="brand-caption">console</span></span>
        </Link>
        <div className="auth-brand-copy">
          <span className="eyebrow">Human Alignment Index</span>
          <h2>Evidence behind every score.</h2>
          <p>Public and submitted evidence about an organization becomes a traceable, reproducible assessment of how it governs AI. The model proposes, the rules decide, a named reviewer signs.</p>
          <ul className="auth-pillars" aria-label="The six pillars">
            {PILLARS.map((p) => <li key={p.code}><span className="pillar-dot" />{p.name}</li>)}
          </ul>
        </div>
        <div className="auth-brand-foot">
          <span>Ontology {ONTOLOGY_VERSION}<span className="footer-separator">/</span>Methodology {METHODOLOGY_VERSION}</span>
          <Link to="/verify"><Icon name="shield" />Verify a certificate</Link>
        </div>
      </aside>
      <div className="auth-main">
        <main id="main" className="auth-content" tabIndex={-1}><Outlet /></main>
        <footer className="auth-footer">
          <span><span className="footer-dot" />Humaital HAI Score Console</span>
          <div className="theme-control light"><Icon name="sun" /><label className="sr-only" htmlFor="public-theme">Theme</label><select id="public-theme" value={theme} onChange={(e) => setTheme(e.target.value as Theme)}><option value="system">System theme</option><option value="light">Light theme</option><option value="dark">Dark theme</option></select></div>
        </footer>
      </div>
    </div>
  );
}
