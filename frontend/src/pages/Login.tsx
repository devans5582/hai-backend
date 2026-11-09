import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon";
import { api, ApiRequestError } from "../lib/api";
import { saveCredentials } from "../lib/auth";

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const from = (location.state as { from?: string } | null)?.from;
  const status = useQuery({ queryKey: ["auth-status"], queryFn: api.authStatus, retry: false, staleTime: 30_000 });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [reviewerToken, setReviewerToken] = useState("");

  const destination = from && from !== "/login" && from !== "/signup" ? from : "/";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    try {
      const result = await api.login({ email: email.trim(), password, remember_me: remember });
      saveCredentials({ session: result.token, apiKey: null, reviewerToken: null });
      queryClient.clear();
      navigate(destination, { replace: true });
    } catch (err) {
      if (err instanceof ApiRequestError) {
        const lockedUntil = err.details["locked_until"];
        setError(typeof lockedUntil === "string" ? `${err.message} (until ${new Date(lockedUntil).toLocaleTimeString()}).` : err.message);
      } else setError("The sign-in service could not be reached. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  const useCredentials = (e: FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim() && !reviewerToken.trim()) {
      setError("Paste an API key or a reviewer token.");
      return;
    }
    saveCredentials({ session: null, apiKey: apiKey.trim() || null, reviewerToken: reviewerToken.trim() || null });
    queryClient.clear();
    navigate(destination, { replace: true });
  };

  return (
    <div className="auth-card-wrap">
      {status.data && !status.data.bootstrapped && (
        <div className="alert info auth-setup-note"><Icon name="sparkles" /><div><strong>This platform has no owner yet.</strong><p>Create the first administrator account to set up the console.</p><Link className="btn primary" to="/signup">Set up the platform<Icon name="arrow-right" /></Link></div></div>
      )}
      <form className="card auth-card" onSubmit={(e) => void submit(e)} noValidate aria-labelledby="login-title">
        <span className="eyebrow">Welcome back</span>
        <h1 id="login-title">Sign in</h1>
        <p className="page-description">Use the email address you were invited with.</p>
        {error && <div className="alert error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="username" value={email} onChange={(e) => { setEmail(e.target.value); setError(null); }} placeholder="you@organization.com" aria-invalid={!!error && !email.trim()} autoFocus />
        </div>
        <div className="field">
          <div className="label-row"><label htmlFor="password">Password</label></div>
          <div className="input-action">
            <input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={(e) => { setPassword(e.target.value); setError(null); }} aria-invalid={!!error && !password} />
            <button type="button" className="icon-button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword}><Icon name={showPassword ? "eye-off" : "eye"} /></button>
          </div>
        </div>
        <label className="checkbox-card remember"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /><span><strong>Keep me signed in</strong><span className="help">Stay signed in on this device for 30 days instead of 12 hours.</span></span></label>
        <button type="submit" className="primary auth-submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}<Icon name="arrow-right" /></button>
        <p className="small muted auth-help">Forgot your password? Ask your administrator for a reset link.</p>
        <div className="auth-links">
          <span>Have an invitation? <Link to="/signup">Create your account</Link></span>
          <span>New here? <Link to="/signup">Request access</Link></span>
        </div>
      </form>
      <details className="card auth-alt">
        <summary><Icon name="key" /><span>Use an API key or reviewer token instead</span><span className="small muted">For partners and operators</span></summary>
        <form onSubmit={useCredentials} className="stack">
          <p className="small muted">These credentials stay in this browser and are sent with every request. Console sign-in gives you a profile, team management and account-owned keys.</p>
          <div className="field">
            <label htmlFor="alt-api-key">API key</label>
            <input id="alt-api-key" type="password" autoComplete="off" spellCheck={false} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="hai_xxxxxxxxxxxx.secret" />
          </div>
          <div className="field">
            <label htmlFor="alt-token">Reviewer token (JWT)</label>
            <input id="alt-token" type="password" autoComplete="off" spellCheck={false} value={reviewerToken} onChange={(e) => setReviewerToken(e.target.value)} placeholder="Paste a token minted by an administrator" />
          </div>
          <div className="actions"><button type="submit">Continue with credentials</button></div>
        </form>
      </details>
    </div>
  );
}
