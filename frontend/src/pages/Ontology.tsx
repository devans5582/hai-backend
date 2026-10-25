import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, QueryState, Tabs } from "../components/widgets";
import { CRITERIA, ENTITIES, INTEGRITY_CONSTRAINTS, LABELS, MANIFEST_HASH, METHODOLOGY_VERSION, ONTOLOGY_VERSION, PILLARS, RULES } from "../generated/ontology";
import { api } from "../lib/api";

type Tab = "entities" | "vocabularies" | "criteria" | "rules" | "constraints";

export function Ontology() {
  const [tab, setTab] = useState<Tab>("criteria");
  const [vocab, setVocab] = useState("coverage_state");
  const live = useQuery({ queryKey: ["ontology"], queryFn: api.ontology });
  const voc = useQuery({ queryKey: ["vocabulary", vocab], queryFn: () => api.vocabulary(vocab), enabled: tab === "vocabularies" });
  const drift = live.data && live.data.manifest_hash !== MANIFEST_HASH;
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Ontology browser</h1>
        <div className="row small muted mono">
          <span>ontology {ONTOLOGY_VERSION}</span>
          <span>methodology {METHODOLOGY_VERSION}</span>
          <span>manifest {MANIFEST_HASH.slice(0, 12)}</span>
        </div>
      </div>
      {drift && (
        <div className="alert error" role="alert">
          The API serves manifest {live.data?.manifest_hash.slice(0, 12)} but this console was built from {MANIFEST_HASH.slice(0, 12)}. Rebuild the console.
        </div>
      )}
      <Tabs<Tab>
        tabs={[
          { id: "criteria", label: "Criteria" },
          { id: "entities", label: "Entities" },
          { id: "vocabularies", label: "Vocabularies" },
          { id: "rules", label: "Rules" },
          { id: "constraints", label: "Integrity constraints" },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "criteria" && (
        <div role="tabpanel" id="panel-criteria" aria-labelledby="tab-criteria" className="stack">
          {PILLARS.map((p) => (
            <section key={p.code} className="card" aria-labelledby={`pillar-${p.code}`}>
              <h2 id={`pillar-${p.code}`}>
                {p.name} <span className="muted small">weight {p.weight}</span>
              </h2>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Name</th>
                      <th>Materiality</th>
                      <th>Freshness</th>
                      <th>Status</th>
                      <th>Ladder</th>
                    </tr>
                  </thead>
                  <tbody>
                    {CRITERIA.filter((c) => c.pillar === p.code).map((c) => (
                      <tr key={c.code}>
                        <td className="mono">{c.code}</td>
                        <td>
                          {c.name}
                          <div className="small muted">{c.legacy_id}</div>
                        </td>
                        <td>
                          {c.materiality} ({c.materiality_weight})
                        </td>
                        <td>{c.freshness_window_months} months</td>
                        <td>
                          <Badge tone={c.content_status === "approved" ? "ok" : "warn"}>{c.content_status}</Badge>
                        </td>
                        <td className="small">{c.levels.map((l) => `${l.level}: ${LABELS["maturity_rung"]?.[l.required_maturity_rung]}`).join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}
      {tab === "entities" && (
        <div role="tabpanel" id="panel-entities" aria-labelledby="tab-entities" className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Entity</th>
                <th>Layer</th>
                <th>Table</th>
                <th>Mutability</th>
                <th>Writers</th>
                <th>Fields</th>
              </tr>
            </thead>
            <tbody>
              {ENTITIES.map((e) => (
                <tr key={e.name}>
                  <td>
                    <strong>{e.name}</strong>
                    <div className="small muted">{e.description}</div>
                  </td>
                  <td>{e.layer}</td>
                  <td className="mono">{e.table}</td>
                  <td>{e.mutability}</td>
                  <td className="small">{e.writers.join(", ")}</td>
                  <td>{e.fields.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "vocabularies" && (
        <div role="tabpanel" id="panel-vocabularies" aria-labelledby="tab-vocabularies" className="card">
          <div className="field">
            <label htmlFor="vocab">Vocabulary</label>
            <select id="vocab" value={vocab} onChange={(e) => setVocab(e.target.value)} style={{ width: "auto" }}>
              {Object.keys(LABELS)
                .sort()
                .map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
            </select>
          </div>
          <QueryState isLoading={voc.isLoading} error={voc.error}>
            {voc.data && (
              <>
                <p className="muted">{voc.data.description}</p>
                <table>
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Label</th>
                      <th>Description</th>
                      <th>Attributes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {voc.data.values.map((v) => (
                      <tr key={v.code}>
                        <td className="mono">{v.code}</td>
                        <td>{v.label}</td>
                        <td>{v.description}</td>
                        <td className="small mono">{v.attributes ? JSON.stringify(v.attributes) : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </QueryState>
        </div>
      )}
      {tab === "rules" && (
        <div role="tabpanel" id="panel-rules" aria-labelledby="tab-rules" className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Order</th>
                <th>Code</th>
                <th>Kind</th>
                <th>Scope</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {[...RULES].sort((a, b) => a.run_order - b.run_order).map((r) => (
                <tr key={r.code}>
                  <td>{r.run_order}</td>
                  <td className="mono">{r.code}</td>
                  <td>{r.kind}</td>
                  <td>{r.scope}</td>
                  <td>{r.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "constraints" && (
        <div role="tabpanel" id="panel-constraints" aria-labelledby="tab-constraints" className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Id</th>
                <th>Rule</th>
                <th>Enforced in</th>
                <th>Implementation</th>
                <th>Test</th>
              </tr>
            </thead>
            <tbody>
              {INTEGRITY_CONSTRAINTS.map((ic) => (
                <tr key={ic.id}>
                  <td className="mono">{ic.id}</td>
                  <td>{ic.rule}</td>
                  <td>{ic.enforced_in}</td>
                  <td className="small mono">{ic.implementation}</td>
                  <td className="mono">{ic.acceptance_test}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
