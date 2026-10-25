import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, QueryState } from "../components/widgets";
import { api } from "../lib/api";
import { fmtDate, fmtNum } from "../lib/format";

export function Verify() {
  const [params, setParams] = useSearchParams();
  const number = params.get("number") ?? "";
  const [input, setInput] = useState(number);
  const q = useQuery({ queryKey: ["verify", number], queryFn: () => api.verifyCertificate(number), enabled: number.length > 3, retry: false });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams({ number: input.trim() });
  };
  return (
    <div className="stack" style={{ maxWidth: 640 }}>
      <h1>Verify a certificate</h1>
      <p className="muted">Public. Enter the certificate number printed on the badge. A valid certificate has a reviewer signature that matches the stored result and has not expired or been revoked.</p>
      <form className="card row" onSubmit={submit} style={{ alignItems: "flex-end" }}>
        <div className="field" style={{ margin: 0, flex: 1 }}>
          <label htmlFor="number">Certificate number</label>
          <input id="number" value={input} onChange={(e) => setInput(e.target.value)} placeholder="HAI-2026-ABC123-0F1E" />
        </div>
        <button type="submit" className="primary">
          Verify
        </button>
      </form>
      {number && (
        <QueryState isLoading={q.isLoading} error={q.error && (q.error as { status?: number }).status !== 404 ? q.error : null}>
          {(q.error as { status?: number } | null)?.status === 404 && (
            <div className="alert error" role="alert">
              No certificate with that number.
            </div>
          )}
          {q.data && (
            <div className="card" role="status">
              <div className="row">
                <Badge tone={q.data.valid ? "ok" : "bad"}>{q.data.valid ? "Valid" : q.data.status}</Badge>
                <span className="mono">{q.data.certificate_number}</span>
              </div>
              <dl>
                <dt>Organization</dt>
                <dd>{q.data.organization ?? "n/a"}</dd>
                <dt>HAI Score at signing</dt>
                <dd>{fmtNum(q.data.hai_score)}</dd>
                <dt>Signed</dt>
                <dd>
                  {fmtDate(q.data.signed_at)} by {q.data.reviewer ?? "n/a"}
                </dd>
                <dt>Expires</dt>
                <dd>{q.data.expires_at ? fmtDate(q.data.expires_at) : "n/a"}</dd>
                <dt>Methodology</dt>
                <dd>{q.data.methodology_version ?? "n/a"}</dd>
              </dl>
            </div>
          )}
        </QueryState>
      )}
    </div>
  );
}
