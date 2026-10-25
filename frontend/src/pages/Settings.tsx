import { useState, type FormEvent } from "react";
import { Badge } from "../components/widgets";
import { useAuth } from "../lib/auth";

export function Settings() {
  const auth = useAuth();
  const [apiKey, setApiKey] = useState(auth.apiKey ?? "");
  const [token, setToken] = useState(auth.reviewerToken ?? "");
  const [saved, setSaved] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    auth.save({ apiKey: apiKey.trim() || null, reviewerToken: token.trim() || null });
    setSaved(true);
  };
  const expires = auth.claims?.exp ? new Date(auth.claims.exp * 1000) : null;
  return (
    <div className="stack" style={{ maxWidth: 680 }}>
      <h1>Settings</h1>
      <p className="muted">Credentials stay in this browser. A reviewer token takes precedence over an API key. API keys can start assessments and read results; only a reviewer token can review or sign.</p>
      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="apiKey">API key</label>
          <input id="apiKey" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="hai_xxxxxxxxxxxx.secret" autoComplete="off" />
          <div className="help">Created with `hai-db create-api-key`. Shown once at creation.</div>
        </div>
        <div className="field">
          <label htmlFor="token">Reviewer token (JWT)</label>
          <textarea id="token" rows={3} value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
          <div className="help">Minted by an admin with POST /v1/auth/token.</div>
        </div>
        <div className="actions">
          <button type="submit" className="primary">
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              setApiKey("");
              setToken("");
              auth.save({ apiKey: null, reviewerToken: null });
              setSaved(true);
            }}
          >
            Clear
          </button>
        </div>
        {saved && (
          <p role="status" className="small muted" style={{ marginTop: "0.5rem" }}>
            Saved.
          </p>
        )}
      </form>
      <div className="card">
        <h2>Current principal</h2>
        {auth.claims ? (
          <p>
            <Badge tone="red">{auth.claims.role}</Badge> {auth.claims.name ?? auth.claims.sub}
            {expires && <span className="muted small"> (expires {expires.toLocaleString()})</span>}
            <br />
            <span className="small muted">scopes: {(auth.claims.scopes ?? []).join(", ")}</span>
          </p>
        ) : auth.apiKey ? (
          <p>
            <Badge>API key</Badge> {auth.apiKey.split(".")[0]}
          </p>
        ) : (
          <p className="muted">Not signed in.</p>
        )}
      </div>
    </div>
  );
}
