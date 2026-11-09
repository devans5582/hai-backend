import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Badge, QueryState } from "../components/widgets";
import { api, ApiRequestError, type Account, type Invitation } from "../lib/api";
import { saveCredentials } from "../lib/auth";
import { fmtDateTime } from "../lib/format";

const MIN_PASSWORD = 10;

function errorText(err: unknown, fallback: string): { message: string; fields: Record<string, string> } {
  if (err instanceof ApiRequestError) return { message: err.message, fields: err.fieldErrors };
  return { message: fallback, fields: {} };
}

/** Three doors: accept an invitation (or reset), set up the first owner, or request access. */
export function Signup() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const status = useQuery({ queryKey: ["auth-status"], queryFn: api.authStatus, retry: false, enabled: !token });
  if (token) return <AcceptInvitation token={token} />;
  return (
    <div className="auth-card-wrap">
      <QueryState isLoading={status.isLoading} error={status.error}>
        {status.data?.bootstrapped === false ? <Bootstrap /> : <RequestAccess />}
      </QueryState>
    </div>
  );
}

function PasswordFields({ password, confirm, setPassword, setConfirm, fields, email }: { password: string; confirm: string; setPassword: (v: string) => void; setConfirm: (v: string) => void; fields: Record<string, string>; email?: string }) {
  const [show, setShow] = useState(false);
  const mismatch = confirm.length > 0 && confirm !== password;
  return (
    <>
      <div className="field">
        <label htmlFor="new-password">Password</label>
        <div className="input-action">
          <input id="new-password" type={show ? "text" : "password"} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-describedby="password-help" aria-invalid={!!fields["password"]} />
          <button type="button" className="icon-button" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}><Icon name={show ? "eye-off" : "eye"} /></button>
        </div>
        {fields["password"] ? <div className="error">{fields["password"]}</div> : <div id="password-help" className="help">At least {MIN_PASSWORD} characters{email ? ", and not your email address" : ""}.</div>}
      </div>
      <div className="field">
        <label htmlFor="confirm-password">Confirm password</label>
        <input id="confirm-password" type={show ? "text" : "password"} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={mismatch} />
        {mismatch && <div className="error">The passwords do not match.</div>}
      </div>
    </>
  );
}

function AcceptInvitation({ token }: { token: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const invitation = useQuery<Invitation & { account: Account }>({ queryKey: ["invitation", token], queryFn: () => api.invitationByToken(token), retry: false });
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const reset = invitation.data?.kind === "password_reset";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setFields({});
    if (!reset && !name.trim()) { setFields({ name: "Enter your name." }); return; }
    if (password.length < MIN_PASSWORD) { setFields({ password: `Use at least ${MIN_PASSWORD} characters.` }); return; }
    if (password !== confirm) { setError("The passwords do not match."); return; }
    setBusy(true);
    try {
      const result = await api.register({ token, name: name.trim(), password });
      saveCredentials({ session: result.token, apiKey: null, reviewerToken: null });
      queryClient.clear();
      navigate("/", { replace: true });
    } catch (err) {
      const parsed = errorText(err, "Registration could not be completed. Try again in a moment.");
      setError(Object.keys(parsed.fields).length ? null : parsed.message);
      setFields(parsed.fields);
    } finally {
      setBusy(false);
    }
  };

  if (invitation.error) {
    const err = invitation.error as ApiRequestError;
    const gone = err.status === 409 ? String(err.details["status"] ?? "no longer valid") : "not found";
    return (
      <div className="auth-card-wrap">
        <div className="card auth-card">
          <span className="eyebrow">Invitation</span>
          <h1>This link is {gone === "not found" ? "not valid" : gone}</h1>
          <p className="page-description">{gone === "accepted" ? "This invitation has already been used. Sign in with the account you created." : gone === "expired" ? "Invitation links expire. Ask the person who invited you for a new one." : gone === "revoked" ? "This invitation was withdrawn. Ask the person who invited you for a new one." : "Check that you copied the whole link, or ask the person who invited you for a new one."}</p>
          <div className="auth-links"><Link className="btn primary" to="/login">Go to sign in<Icon name="arrow-right" /></Link><Link className="btn" to="/signup">Request access</Link></div>
        </div>
      </div>
    );
  }
  return (
    <div className="auth-card-wrap">
      <QueryState isLoading={invitation.isLoading} error={null}>
        {invitation.data && (
          <form className="card auth-card" onSubmit={(e) => void submit(e)} noValidate aria-labelledby="signup-title">
            <span className="eyebrow">{reset ? "Password reset" : "You're invited"}</span>
            <h1 id="signup-title">{reset ? "Choose a new password" : `Join ${invitation.data.account.name}`}</h1>
            <p className="page-description">{reset ? "Your other sessions will be signed out once the new password is saved." : invitation.data.account.kind === "organization" ? "You will see your organization's HAI Score reports and the evidence behind them." : "You will work in the Humaital governance workspace."}</p>
            <dl className="invite-facts">
              <div><dt>Email</dt><dd>{invitation.data.email}</dd></div>
              <div><dt>Role</dt><dd><Badge tone="red">{invitation.data.role_label}</Badge></dd></div>
              {invitation.data.industries.length > 0 && <div><dt>Industries</dt><dd>{invitation.data.industries.join(", ")}</dd></div>}
              {invitation.data.invited_by_name && <div><dt>Invited by</dt><dd>{invitation.data.invited_by_name}</dd></div>}
              <div><dt>Link expires</dt><dd>{fmtDateTime(invitation.data.expires_at)}</dd></div>
            </dl>
            {invitation.data.message && <blockquote className="quote">{invitation.data.message}</blockquote>}
            {error && <div className="alert error" role="alert">{error}</div>}
            {!reset && (
              <div className="field">
                <label htmlFor="full-name">Your name</label>
                <input id="full-name" autoComplete="name" value={name} onChange={(e) => { setName(e.target.value); setFields({}); }} aria-invalid={!!fields["name"]} autoFocus />
                {fields["name"] && <div className="error">{fields["name"]}</div>}
                <div className="help">Shown on reviews and certification decisions you make.</div>
              </div>
            )}
            <PasswordFields password={password} confirm={confirm} setPassword={(v) => { setPassword(v); setFields({}); }} setConfirm={setConfirm} fields={fields} email={invitation.data.email} />
            <button type="submit" className="primary auth-submit" disabled={busy}>{busy ? "Saving…" : reset ? "Save new password" : "Create account"}<Icon name="arrow-right" /></button>
            <div className="auth-links"><span>Already have an account? <Link to="/login">Sign in</Link></span></div>
          </form>
        )}
      </QueryState>
    </div>
  );
}

function Bootstrap() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [platform, setPlatform] = useState("Humaital");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setFields({});
    const missing: Record<string, string> = {};
    if (!name.trim()) missing["name"] = "Enter your name.";
    if (!email.trim()) missing["email"] = "Enter your email.";
    if (password.length < MIN_PASSWORD) missing["password"] = `Use at least ${MIN_PASSWORD} characters.`;
    if (Object.keys(missing).length) { setFields(missing); return; }
    if (password !== confirm) { setError("The passwords do not match."); return; }
    setBusy(true);
    try {
      const result = await api.bootstrap({ email: email.trim(), name: name.trim(), password, platform_name: platform.trim() || "Humaital" });
      saveCredentials({ session: result.token, apiKey: null, reviewerToken: null });
      queryClient.clear();
      navigate("/", { replace: true });
    } catch (err) {
      const parsed = errorText(err, "Setup could not be completed. Try again in a moment.");
      setError(Object.keys(parsed.fields).length ? null : parsed.message);
      setFields(parsed.fields);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="card auth-card" onSubmit={(e) => void submit(e)} noValidate aria-labelledby="bootstrap-title">
      <span className="eyebrow">First-run setup</span>
      <h1 id="bootstrap-title">Set up the platform</h1>
      <p className="page-description">Create the first owner account. The owner invites administrators, reviewers, analysts and participating organizations from the Team page.</p>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="field">
        <label htmlFor="platform-name">Platform name</label>
        <input id="platform-name" value={platform} onChange={(e) => setPlatform(e.target.value)} />
      </div>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="owner-name">Your name</label>
          <input id="owner-name" autoComplete="name" value={name} onChange={(e) => { setName(e.target.value); setFields({}); }} aria-invalid={!!fields["name"]} />
          {fields["name"] && <div className="error">{fields["name"]}</div>}
        </div>
        <div className="field">
          <label htmlFor="owner-email">Work email</label>
          <input id="owner-email" type="email" autoComplete="username" value={email} onChange={(e) => { setEmail(e.target.value); setFields({}); }} aria-invalid={!!fields["email"]} />
          {fields["email"] && <div className="error">{fields["email"]}</div>}
        </div>
      </div>
      <PasswordFields password={password} confirm={confirm} setPassword={(v) => { setPassword(v); setFields({}); }} setConfirm={setConfirm} fields={fields} email={email} />
      <button type="submit" className="primary auth-submit" disabled={busy}>{busy ? "Creating…" : "Create owner account"}<Icon name="arrow-right" /></button>
      <div className="auth-links"><span>Already set up? <Link to="/login">Sign in</Link></span></div>
    </form>
  );
}

function RequestAccess() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [organization, setOrganization] = useState("");
  const [website, setWebsite] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const missing: Record<string, string> = {};
    if (!name.trim()) missing["name"] = "Enter your name.";
    if (!email.trim()) missing["email"] = "Enter your work email.";
    if (!organization.trim()) missing["organization_name"] = "Enter your organization.";
    setFields(missing);
    if (Object.keys(missing).length) return;
    setBusy(true);
    try {
      await api.requestAccess({ email: email.trim(), name: name.trim(), organization_name: organization.trim(), website: website.trim() || undefined, message: message.trim() || undefined });
      setDone(true);
    } catch (err) {
      const parsed = errorText(err, "The request could not be sent. Try again in a moment.");
      setError(Object.keys(parsed.fields).length ? null : parsed.message);
      setFields(parsed.fields);
    } finally {
      setBusy(false);
    }
  };
  if (done) {
    return (
      <div className="card auth-card auth-done">
        <span className="verify-symbol"><Icon name="check-circle" /></span>
        <h1>Request sent</h1>
        <p className="page-description">Humaital reviews every request. When yours is approved you will receive an invitation link for <strong>{email.trim()}</strong>; open it to create your account.</p>
        <div className="auth-links"><Link className="btn primary" to="/login">Back to sign in<Icon name="arrow-right" /></Link></div>
      </div>
    );
  }
  return (
    <form className="card auth-card" onSubmit={(e) => void submit(e)} noValidate aria-labelledby="request-title">
      <span className="eyebrow">Create an account</span>
      <h1 id="request-title">Request access</h1>
      <p className="page-description">Accounts are created by invitation. Tell us who you are and which organization you represent; participating organizations sign in with their work email to see their reports.</p>
      <div className="alert info auth-invite-note"><Icon name="mail" /><p>Already have an invitation link? Open it to create your account right away.</p></div>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="form-grid">
        <div className="field">
          <label htmlFor="req-name">Your name</label>
          <input id="req-name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!fields["name"]} />
          {fields["name"] && <div className="error">{fields["name"]}</div>}
        </div>
        <div className="field">
          <label htmlFor="req-email">Work email</label>
          <input id="req-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!fields["email"]} />
          {fields["email"] && <div className="error">{fields["email"]}</div>}
        </div>
      </div>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="req-org">Organization</label>
          <input id="req-org" autoComplete="organization" value={organization} onChange={(e) => setOrganization(e.target.value)} aria-invalid={!!fields["organization_name"]} />
          {fields["organization_name"] && <div className="error">{fields["organization_name"]}</div>}
        </div>
        <div className="field">
          <label htmlFor="req-website">Website <span className="muted">(optional)</span></label>
          <input id="req-website" autoComplete="url" value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="organization.com" />
        </div>
      </div>
      <div className="field">
        <label htmlFor="req-message">What do you need access for? <span className="muted">(optional)</span></label>
        <textarea id="req-message" rows={3} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="For example: we were assessed last quarter and want to see the report." />
      </div>
      <button type="submit" className="primary auth-submit" disabled={busy}>{busy ? "Sending…" : "Send request"}<Icon name="arrow-right" /></button>
      <div className="auth-links"><span>Already have an account? <Link to="/login">Sign in</Link></span></div>
    </form>
  );
}
