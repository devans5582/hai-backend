import { useMutation } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Field } from "../components/widgets";
import { LABELS, SIZE_BAND_VALUES, STAGE_BAND_VALUES } from "../generated/ontology";
import { api, ApiRequestError, idempotencyKey } from "../lib/api";

export function NewAssessment() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ organization_name: "", website: "", stage: "growth", size: "mid", industry: "", direct_urls: "", certification_requested: false });
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({});
  const [detailsOpen, setDetailsOpen] = useState(false);
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
  const fieldErrors = { ...err?.fieldErrors, ...localErrors };
  const generic = create.error && Object.keys(fieldErrors).length === 0 ? create.error.message : null;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => {
    setForm((current) => ({ ...current, [k]: e.target.value }));
    setLocalErrors((current) => {
      const next = { ...current };
      delete next[k];
      return next;
    });
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const errors: Record<string, string> = {};
    if (!form.organization_name.trim()) errors.organization_name = "Enter the organization's name.";
    if (!form.website.trim()) errors.website = "Enter the organization's official website.";
    setLocalErrors(errors);
    const firstInvalidField = Object.keys(errors)[0];
    if (firstInvalidField) {
      document.getElementById(firstInvalidField)?.focus();
      return;
    }
    create.mutate();
  };
  const stageError = fieldErrors["stage"] ?? fieldErrors["fields.stage"];
  const sizeError = fieldErrors["size"] ?? fieldErrors["fields.size"];

  return (
    <div className="stack assessment-create">
      <Link to="/" className="text-link"><Icon name="arrow-left" /> Back to dashboard</Link>
      <div className="page-head">
        <div>
          <span className="eyebrow">Build a clearer picture</span>
          <h1>New assessment</h1>
          <p className="page-description">Understand how an organization governs AI, with evidence behind every score.</p>
        </div>
      </div>
      <div className="form-layout">
        <form className="card form-main" onSubmit={submit} noValidate aria-describedby={generic ? "form-error" : undefined} aria-busy={create.isPending}>
          {generic && <div className="alert error" role="alert" id="form-error">{generic}</div>}
          <section className="form-section" aria-labelledby="organization-heading">
            <div className="section-heading">
              <span className="step-number">01</span>
              <div><h2 id="organization-heading">Organization details</h2><p className="muted small">Tell us who you would like to assess.</p></div>
            </div>
            <Field id="organization_name" label="Organization name" error={fieldErrors["organization_name"]}>
              <input id="organization_name" value={form.organization_name} onChange={set("organization_name")} required placeholder="e.g. Acme Corporation" autoComplete="organization" aria-invalid={!!fieldErrors["organization_name"]} aria-describedby={fieldErrors["organization_name"] ? "organization_name-error" : undefined} />
            </Field>
            <Field id="website" label="Official website" error={fieldErrors["website"]} help="Enter a domain or full URL. We use it to find the right organization and its public evidence.">
              <input id="website" value={form.website} onChange={set("website")} required placeholder="e.g. acme.com" autoComplete="url" autoCapitalize="none" spellCheck={false} aria-invalid={!!fieldErrors["website"]} aria-describedby={fieldErrors["website"] ? "website-error" : "website-help"} />
            </Field>
          </section>

          <section className="form-section" aria-labelledby="context-heading">
            <div className="section-heading">
              <span className="step-number">02</span>
              <div><h2 id="context-heading">Organization context</h2><p className="muted small">Choose the closest fit for a fair assessment.</p></div>
            </div>
            <div className="form-grid">
              <Field id="stage" label="Stage" error={stageError}>
                <select id="stage" value={form.stage} onChange={set("stage")} aria-invalid={!!stageError} aria-describedby={stageError ? "stage-error" : undefined}>
                  {STAGE_BAND_VALUES.map((v) => <option key={v} value={v}>{LABELS["stage_band"]?.[v] ?? v}</option>)}
                </select>
              </Field>
              <Field id="size" label="Size" error={sizeError}>
                <select id="size" value={form.size} onChange={set("size")} aria-invalid={!!sizeError} aria-describedby={sizeError ? "size-error" : undefined}>
                  {SIZE_BAND_VALUES.map((v) => <option key={v} value={v}>{LABELS["size_band"]?.[v] ?? v}</option>)}
                </select>
              </Field>
            </div>
            <details className="optional-details" open={detailsOpen || !!fieldErrors["industry"] || !!fieldErrors["direct_urls"]} onToggle={(e) => setDetailsOpen(e.currentTarget.open)}>
              <summary><Icon name="plus" /> Add industry and evidence links <span className="muted small">Optional</span></summary>
              <div className="stack">
                <Field id="industry" label="Industry (optional)" error={fieldErrors["industry"]} help="Helps you compare results with similar organizations.">
                  <input id="industry" value={form.industry} onChange={set("industry")} placeholder="e.g. Financial services" aria-invalid={!!fieldErrors["industry"]} aria-describedby={fieldErrors["industry"] ? "industry-error" : "industry-help"} />
                </Field>
                <Field id="direct_urls" label="Governance page URLs (optional)" error={fieldErrors["direct_urls"]} help="Add links to AI policies, transparency reports, or other governance evidence. Use one URL per line.">
                  <textarea id="direct_urls" rows={3} value={form.direct_urls} onChange={set("direct_urls")} placeholder="https://acme.com/responsible-ai" autoCapitalize="none" spellCheck={false} aria-invalid={!!fieldErrors["direct_urls"]} aria-describedby={fieldErrors["direct_urls"] ? "direct_urls-error" : "direct_urls-help"} />
                </Field>
              </div>
            </details>
          </section>

          <section className="form-section" aria-labelledby="certification-heading">
            <label className="checkbox-card" htmlFor="certification_requested">
              <input id="certification_requested" type="checkbox" checked={form.certification_requested} onChange={(e) => setForm({ ...form, certification_requested: e.target.checked })} aria-describedby="certification-help" />
              <span><strong id="certification-heading">Request a certification decision from a reviewer</strong><span id="certification-help" className="help">A named reviewer will assess eligibility and sign the final decision.</span></span>
            </label>
          </section>
          <div className="form-footer">
            <Link to="/" className="btn">Cancel</Link>
            <button type="submit" className="primary" disabled={create.isPending}>{create.isPending ? "Starting..." : "Start assessment"}<Icon name="arrow-right" /></button>
          </div>
        </form>

        <aside className="form-aside">
          <div className="card">
            <span className="eyebrow">From evidence to understanding</span>
            <h2>What happens next?</h2>
            <ol className="journey-list">
              <li><span className="step-number"><Icon name="globe" /></span><div><h3>Gather the evidence</h3><p>We collect public policies, reports, and other relevant sources.</p></div></li>
              <li><span className="step-number"><Icon name="layers" /></span><div><h3>Assess six pillars</h3><p>Consistent rules evaluate 20 criteria across AI governance.</p></div></li>
              <li><span className="step-number"><Icon name="shield" /></span><div><h3>Explore your results</h3><p>See the score, confidence, and evidence behind each decision.</p></div></li>
            </ol>
          </div>
          <div className="alert info"><Icon name="info" /><p className="small">You can follow progress from the assessment page. Anything that needs human judgment is sent to the review queue.</p></div>
        </aside>
      </div>
    </div>
  );
}
