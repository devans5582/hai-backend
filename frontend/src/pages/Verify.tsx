import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Badge, QueryState } from "../components/widgets";
import { api } from "../lib/api";
import { fmtDate, fmtNum } from "../lib/format";

export function Verify() {
  const [params, setParams] = useSearchParams();
  const number = params.get("number") ?? "";
  const [input, setInput] = useState(number);
  const [validation, setValidation] = useState("");
  const q = useQuery({ queryKey: ["verify", number], queryFn: () => api.verifyCertificate(number), enabled: number.length > 3, retry: false });
  useEffect(() => { setInput(number); setValidation(""); }, [number]);
  const error = validation || (number && number.length <= 3 ? "Enter a complete certificate number." : "");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = input.trim();
    if (value.length <= 3) {
      setValidation("Enter a complete certificate number.");
      return;
    }
    setValidation("");
    if (value === number) void q.refetch();
    else setParams({ number: value });
  };
  return (
    <div className="stack verify-page">
      <div className="verify-intro">
        <div className="verify-symbol"><Icon name="shield" /></div>
        <p className="eyebrow">Confidence you can verify</p>
        <h1>Verify a certificate</h1>
        <p className="page-description">Check the authenticity and current status of a HAI Score certificate. No sign-in required.</p>
      </div>
      <form className="card verify-form" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="number">Certificate number</label>
          <div className="verify-input-row">
            <input id="number" value={input} onChange={(e) => { setInput(e.target.value); setValidation(""); }} placeholder="HAI-2026-ABC123-0F1E" autoComplete="off" spellCheck={false} aria-invalid={!!error} aria-describedby={error ? "number-error" : "number-help"} />
            <button type="submit" className="primary" disabled={q.isFetching}><Icon name="search" />{q.isFetching ? "Checking…" : "Verify"}</button>
          </div>
          {error ? <div id="number-error" className="error" role="alert">{error}</div> : <div id="number-help" className="help">Find this number on your certificate or certification badge.</div>}
        </div>
      </form>
      {number.length > 3 ? (
        <QueryState isLoading={q.isLoading} error={q.error && (q.error as { status?: number }).status !== 404 ? q.error : null}>
          {(q.error as { status?: number } | null)?.status === 404 && (
            <div className="alert error" role="alert">
              <strong>No certificate with that number.</strong> Check the number on your certificate and try again.
            </div>
          )}
          {q.data && (
            <div className="card certificate-result" role="status">
              <div className="section-heading"><Icon name={q.data.valid ? "check-circle" : "info"} /><h2>Certificate details</h2><Badge tone={q.data.valid ? "ok" : "bad"}>{q.data.valid ? "Valid" : q.data.status}</Badge></div>
              <p className="mono small muted">{q.data.certificate_number}</p>
              <h3>{q.data.organization ?? "Organization unavailable"}</h3>
              {q.data.valid && <p className="small muted">The reviewer signature matches the stored result. This certificate has not expired or been revoked.</p>}
              <dl className="certificate-facts">
                <div><dt>HAI Score at signing</dt><dd>{fmtNum(q.data.hai_score)}</dd></div>
                <div><dt>Signed</dt><dd>{q.data.signed_at ? fmtDate(q.data.signed_at) : "n/a"}</dd></div>
                <div><dt>Reviewer</dt><dd>{q.data.reviewer ?? "n/a"}</dd></div>
                <div><dt>Expires</dt><dd>{q.data.expires_at ? fmtDate(q.data.expires_at) : "n/a"}</dd></div>
                <div><dt>Methodology</dt><dd>{q.data.methodology_version ?? "n/a"}</dd></div>
              </dl>
            </div>
          )}
        </QueryState>
      ) : (
        <div className="verification-note"><Icon name="lock" /><p className="small muted">Each HAI certificate is linked to an evidence-based assessment and signed by a named reviewer.</p></div>
      )}
    </div>
  );
}
