import { useMutation } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Field } from "../components/widgets";
import { LABELS, SIZE_BAND_VALUES, STAGE_BAND_VALUES } from "../generated/ontology";
import { api, ApiRequestError, idempotencyKey } from "../lib/api";

export function NewAssessment() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ organization_name: "", website: "", stage: "growth", size: "mid", industry: "", direct_urls: "", certification_requested: false });
  const key = useMemo(() => idempotencyKey(), []);
  const create = useMutation({
    mutationFn: () =>
      api.createAssessment(
        {
          organization_name: form.organization_name.trim(),
          website: form.website.trim(),
          stage: form.stage,
          size: form.size,
          industry: form.industry.trim() || undefined,
          direct_urls: form.direct_urls
            .split(/\n|,/)
            .map((s) => s.trim())
            .filter(Boolean),
          certification_requested: form.certification_requested,
        },
        key,
      ),
    onSuccess: (a) => navigate(`/assessments/${a.id}`),
  });
  const err = create.error instanceof ApiRequestError ? create.error : null;
  const fieldErrors = err?.fieldErrors ?? {};
  const generic = err && Object.keys(fieldErrors).length === 0 ? err.message : null;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <div className="stack" style={{ maxWidth: 680 }}>
      <h1>New assessment</h1>
      <p className="muted">The platform fetches public evidence, proposes levels, lets the rules decide, and routes anything uncertain to a reviewer. The same Idempotency-Key is sent on retries so a double submit starts one assessment.</p>
      <form className="card" onSubmit={submit} noValidate aria-describedby={generic ? "form-error" : undefined}>
        {generic && (
          <div className="alert error" role="alert" id="form-error">
            {generic}
          </div>
        )}
        <Field id="organization_name" label="Organization name" error={fieldErrors["organization_name"]}>
          <input id="organization_name" value={form.organization_name} onChange={set("organization_name")} required aria-invalid={!!fieldErrors["organization_name"]} aria-describedby={fieldErrors["organization_name"] ? "organization_name-error" : undefined} />
        </Field>
        <Field id="website" label="Official website" error={fieldErrors["website"]} help="Domain or URL. Identifiers are only stored when registries agree with this domain.">
          <input id="website" value={form.website} onChange={set("website")} required placeholder="acme.example" aria-invalid={!!fieldErrors["website"]} aria-describedby={fieldErrors["website"] ? "website-error" : "website-help"} />
        </Field>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field id="stage" label="Stage" error={fieldErrors["stage"] ?? fieldErrors["fields.stage"]}>
            <select id="stage" value={form.stage} onChange={set("stage")} aria-invalid={!!fieldErrors["stage"]}>
              {STAGE_BAND_VALUES.map((v) => (
                <option key={v} value={v}>
                  {LABELS["stage_band"]?.[v] ?? v}
                </option>
              ))}
            </select>
          </Field>
          <Field id="size" label="Size" error={fieldErrors["size"] ?? fieldErrors["fields.size"]}>
            <select id="size" value={form.size} onChange={set("size")} aria-invalid={!!fieldErrors["size"]}>
              {SIZE_BAND_VALUES.map((v) => (
                <option key={v} value={v}>
                  {LABELS["size_band"]?.[v] ?? v}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field id="industry" label="Industry (optional)" error={fieldErrors["industry"]} help="Used for peer benchmarks.">
          <input id="industry" value={form.industry} onChange={set("industry")} aria-describedby="industry-help" />
        </Field>
        <Field id="direct_urls" label="Governance page URLs (optional)" error={fieldErrors["direct_urls"]} help="One per line. Fetched by the DIRECT_URL connector when a site blocks crawling.">
          <textarea id="direct_urls" rows={3} value={form.direct_urls} onChange={set("direct_urls")} aria-describedby="direct_urls-help" />
        </Field>
        <div className="field row">
          <input id="certification_requested" type="checkbox" style={{ width: "auto" }} checked={form.certification_requested} onChange={(e) => setForm({ ...form, certification_requested: e.target.checked })} />
          <label htmlFor="certification_requested" style={{ margin: 0 }}>
            Request a certification decision from a reviewer
          </label>
        </div>
        <div className="actions">
          <button type="submit" className="primary" disabled={create.isPending}>
            {create.isPending ? "Starting..." : "Start assessment"}
          </button>
        </div>
      </form>
    </div>
  );
}
