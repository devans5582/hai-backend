import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { METHODOLOGY_VERSION, ONTOLOGY_VERSION, PILLARS } from "../generated/ontology";
import { applyTheme, readTheme, type Theme } from "../lib/auth";
import { BrandLogo } from "./BrandLogo";
import { Icon } from "./Icon";
import "./public-layout.css";

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
          <span className="brand-product">HAI Score<span className="brand-caption">Console</span></span>
        </Link>
        <div className="auth-brand-copy">
          <span className="eyebrow"><span className="auth-kicker-line" />Human Alignment Index</span>
          <h2>Evidence behind <br />every <em>score.</em></h2>
          <p>A clearer picture of how organizations govern AI. Built on evidence. Guided by defined rules. Signed by a named reviewer.</p>
          <div className="auth-framework" aria-hidden="true">
            <svg viewBox="0 0 420 180" fill="none">
              <path d="M0 90H420 M210 0V180" stroke="currentColor" strokeOpacity=".08" />
              <ellipse cx="210" cy="90" rx="154" ry="66" stroke="currentColor" strokeOpacity=".14" />
              <ellipse cx="210" cy="90" rx="104" ry="44" stroke="currentColor" strokeOpacity=".12" />
              <path d="m76 57 134 33 134-33 M76 123l134-33 134 33 M210 24v132" stroke="currentColor" strokeOpacity=".2" strokeDasharray="3 5" />
              {[[210, 24], [344, 57], [344, 123], [210, 156], [76, 123], [76, 57]].map(([cx, cy], index) => <g key={index}><circle cx={cx} cy={cy} r="13" fill="#253440" stroke="#52606b" /><circle cx={cx} cy={cy} r="4" fill={index === 0 ? "#ed9a91" : "#b5c4cd"} /></g>)}
              <circle cx="210" cy="90" r="32" fill="#c73542" stroke="#e2848d" strokeWidth=".75" />
              <path d="m210 73-14 6v10c0 10 14 17 14 17s14-7 14-17V79l-14-6Z m-7 16 5 5 9-10" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span>Six pillars. One connected framework.</span>
          </div>
          <ul className="auth-pillars" aria-label="The six pillars">
            {PILLARS.map((p, index) => <li key={p.code}><span className="auth-pillar-number">0{index + 1}</span>{p.name}</li>)}
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
