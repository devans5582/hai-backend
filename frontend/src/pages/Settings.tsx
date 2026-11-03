import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Icon } from "../components/Icon";
import { Badge } from "../components/widgets";
import { useAuth, type Credentials } from "../lib/auth";

export function Settings() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState(auth.apiKey ?? "");
  const [token, setToken] = useState(auth.reviewerToken ?? "");
  const [showKey, setShowKey] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [message, setMessage] = useState("");
  const persist = (credentials: Credentials, confirmation: string) => {
    auth.save(credentials);
    // Reset cached results and authorization errors before fetching with new credentials.
    void queryClient.resetQueries();
    setMessage(confirmation);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    persist({ apiKey: apiKey.trim() || null, reviewerToken: token.trim() || null }, "Credentials saved.");
  };
  const expires = auth.claims?.exp ? new Date(auth.claims.exp * 1000) : null;
  const expired = expires !== null && expires.getTime() < Date.now();
  const connected = !!(auth.apiKey || auth.reviewerToken);
  const changed = apiKey.trim() !== (auth.apiKey ?? "") || token.trim() !== (auth.reviewerToken ?? "");
  return (
    <div className="stack settings-page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Your workspace</p>
          <h1>Settings</h1>
          <p className="page-description">Manage your access to assessments, evidence, and reviews.</p>
        </div>
      </div>
      <div className="settings-grid">
        <form className="card" onSubmit={submit}>
          <div className="section-heading">
            <Icon name="key" />
            <div><h2>Access credentials</h2><p className="muted small">Use an API key or a reviewer token to connect.</p></div>
          </div>
          <div className="form-section">
            <div className="field">
              <label htmlFor="apiKey">API key</label>
              <div className="input-action">
                <input id="apiKey" type={showKey ? "text" : "password"} value={apiKey} onChange={(e) => { setApiKey(e.target.value); setMessage(""); }} placeholder="hai_xxxxxxxxxxxx.secret" autoComplete="off" spellCheck={false} aria-describedby="apiKey-help" />
                <button type="button" className="icon-button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? "Hide API key" : "Show API key"} aria-pressed={showKey}><Icon name={showKey ? "eye-off" : "eye"} /></button>
              </div>
              <div id="apiKey-help" className="help">Start assessments and read results. Ask your administrator for a key.</div>
            </div>
            <div className="field">
              <label htmlFor="token">Reviewer token (JWT)</label>
              <div className="input-action">
                <input id="token" type={showToken ? "text" : "password"} value={token} onChange={(e) => { setToken(e.target.value); setMessage(""); }} placeholder="Paste your reviewer token" autoComplete="off" spellCheck={false} aria-describedby="token-help" />
                <button type="button" className="icon-button" onClick={() => setShowToken(!showToken)} aria-label={showToken ? "Hide reviewer token" : "Show reviewer token"} aria-pressed={showToken}><Icon name={showToken ? "eye-off" : "eye"} /></button>
              </div>
              <div id="token-help" className="help">Review evidence and sign certification decisions. When both are saved, the reviewer token is used.</div>
            </div>
            <div className="credential-note"><Icon name="lock" /><span className="small muted">Credentials are saved in this browser. Clear them when using a shared device.</span></div>
          </div>
          <div className="form-footer">
            <div className="actions">
              <button type="submit" className="primary"><Icon name="check" /> Save credentials</button>
              <button type="button" disabled={!connected && !apiKey && !token} onClick={() => { setApiKey(""); setToken(""); setShowKey(false); setShowToken(false); persist({ apiKey: null, reviewerToken: null }, "Credentials cleared."); }}>Clear credentials</button>
            </div>
            {message ? <p role="status" className="small success-message"><Icon name="check-circle" /> {message}</p> : changed ? <p className="small muted">You have unsaved changes.</p> : null}
          </div>
        </form>
        <aside className="stack">
          <div className="card access-card">
            <div className="section-heading"><Icon name="shield" /><h2>Current access</h2></div>
            <Badge tone={expired ? "warn" : connected ? "ok" : "info"}>{expired ? "Token expired" : connected ? "Credentials saved" : "Not connected"}</Badge>
            {auth.claims ? (
              <>
                <h3>{auth.claims.name ?? auth.claims.sub}</h3>
                <p className="muted small">{auth.claims.role === "admin" ? "Administrator" : auth.claims.role === "reviewer" ? "Reviewer" : "Token access"}</p>
                {expires && <p className="small muted">{expired ? "Expired" : "Expires"} {expires.toLocaleString()}</p>}
                {(auth.claims.scopes ?? []).length > 0 && <p className="small muted">Scopes: {auth.claims.scopes?.join(", ")}</p>}
                {expired && <p className="small">Ask your administrator for a new reviewer token to continue.</p>}
              </>
            ) : auth.reviewerToken ? (
              <p className="small muted">The saved token could not be read. Check that you copied the complete reviewer token.</p>
            ) : auth.apiKey ? (
              <><h3>API key access</h3><p className="muted small">Your key is saved. You can start assessments and read results.</p></>
            ) : (
              <p className="small muted">Add credentials to start an assessment. Certificate verification is available to everyone.</p>
            )}
          </div>
          <div className="card">
            <h3>Need reviewer access?</h3>
            <p className="muted small">Your administrator can provide a named reviewer token. Every review and certification decision is attributed to the person who signs it.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
