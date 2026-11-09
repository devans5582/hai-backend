// Typed API client. Shapes mirror services/api/src/hai_api/schemas.py and the report builder.
import type { CoverageState, CriterionCode, LifecycleState, OutcomeStatus, PillarCode, ReviewAction, ReviewSubjectType } from "../generated/ontology";
import { authHeaders, dropSession, readCredentials } from "./auth";

export interface ApiError {
  status: number;
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export class ApiRequestError extends Error implements ApiError {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
  get fieldErrors(): Record<string, string> {
    const fields = this.details["fields"];
    return fields && typeof fields === "object" ? (fields as Record<string, string>) : {};
  }
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Assessment {
  id: string;
  org_id: string;
  parent_assessment_id: string | null;
  requested_by: string;
  submitted_domain: string;
  direct_urls: string[];
  stage_band: string;
  size_band: string;
  lifecycle_state: LifecycleState;
  lifecycle_label: string;
  certification_requested: boolean;
  failure_reason: string | null;
  versions: Record<string, string>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  links: Record<string, string>;
}

export interface PillarResult {
  code: PillarCode;
  name: string;
  score: number;
  confidence: number;
  criteria_counted: number;
  criteria_excluded: number;
}

export interface Result {
  assessment_id: string;
  result_id: string;
  hai_score: number | null;
  confidence_pct: number | null;
  effectiveness: number | null;
  outcome_status: OutcomeStatus;
  outcome_label: string;
  gate_reasons: string[];
  review_triggers: string[];
  caps_applied: string[];
  score_before_caps: number | null;
  pillars: PillarResult[];
  ruleset_version: string;
  result_sha256: string;
  created_at: string | null;
}

export interface Decision {
  id: string;
  criterion_code: CriterionCode;
  criterion_name: string;
  pillar: PillarCode;
  level: number | null;
  coverage_state: CoverageState;
  coverage_wording: string;
  confidence: number;
  applied_rule_codes: string[];
  review_required: boolean;
  finding_id: string | null;
  created_at: string | null;
}

export interface EvidenceItem {
  link_id: string;
  quote: string;
  polarity: string;
  admissibility: string;
  admissibility_reason?: string | null;
  maturity_rung: string;
  execution_level: string;
  evidence_class: string;
  independence: string;
  source_tier: string;
  publisher_name: string | null;
  publisher_type: string;
  published_at: string | null;
  canonical_url: string | null;
  document_title: string | null;
  section_heading: string | null;
  document_id: string;
  span_id: string;
  char_start: number;
  char_end: number;
  cited_by_finding?: boolean;
  connector_code?: string;
}

export interface RuleTraceEntry {
  rule: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  note: string;
}

export interface CriterionTrace {
  criterion_code: CriterionCode;
  criterion_name: string;
  decision_id: string;
  level: number | null;
  coverage_state: CoverageState;
  confidence: number;
  applied_rule_codes: string[];
  rules: RuleTraceEntry[];
  inputs: Record<string, unknown>;
  caps_applied: string[];
  adjustments: string[];
  finding: { id: string; proposed_level: number; model_id: string; uncertainty: number; reasoning_summary: string } | null;
  evidence: EvidenceItem[];
}

export interface Trace {
  assessment_id: string;
  criteria: CriterionTrace[];
  result?: { hai_score: number | null; outcome_status: string | null; rules: RuleTraceEntry[]; overlay: Record<string, unknown>; result_sha256: string | null };
  snapshot?: { id: string; frozen_at: string; sha256: string; version_pins: Record<string, string> } | null;
}

export interface ConnectorRun {
  id: string;
  code: string;
  name: string;
  outcome: string;
  outcome_label: string;
  items_returned: number;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  notes: string | null;
}

export interface ReportCriterion {
  code: CriterionCode;
  name: string;
  pillar: PillarCode;
  definition: string;
  content_status: string;
  level: number | null;
  level_descriptor: string | null;
  coverage_state: CoverageState | null;
  coverage_wording: string | null;
  confidence: number | null;
  review_required: boolean;
  applied_rule_codes: string[];
  evidence: EvidenceItem[];
  decision_id: string | null;
}

export interface Report {
  product: { report_name: string; long_name: string };
  assessment: Record<string, unknown> & { id: string; lifecycle_state: string; versions: Record<string, string> };
  organization: { id: string; name: string; legal_name: string; domain: string; industry_code: string | null };
  result: {
    hai_score: number | null;
    confidence_pct: number | null;
    effectiveness: number | null;
    outcome_status: OutcomeStatus;
    outcome_label: string;
    gate_reasons: string[];
    review_triggers: string[];
    caps_applied: string[];
  } | null;
  pillars: { code: PillarCode; name: string; weight: number; score: number | null; confidence: number | null; criteria_counted: number; criteria_excluded: number }[];
  criteria: ReportCriterion[];
  coverage_summary: Record<string, number>;
  connector_runs: ConnectorRun[];
  sources: { id: string; canonical_url: string; title: string | null; published_at: string | null; publisher: string; publisher_type: string; connector: string }[];
  execution_notes: { code: string; name: string; note: string }[];
  snapshot: { id: string; frozen_at: string; sha256: string; links: number } | null;
  drafts_notice: string;
}

export interface ReviewTask {
  id: string;
  assessment_id: string | null;
  subject_type: ReviewSubjectType;
  subject_id: string;
  reason: string;
  status: "open" | "escalated" | "closed";
  opened_by: string;
  excluded_reviewers: string[];
  allowed_actions: ReviewAction[];
  closed_by: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Organization {
  id: string;
  legal_name: string;
  display_name: string;
  primary_domain: string;
  aliases: string[];
  industry_code: string | null;
  stage_band: string | null;
  size_band: string | null;
  identifiers: Record<string, string | null>;
  identifiers_verified: boolean;
  entity_confidence: number | null;
  created_at: string | null;
}

export interface Verification {
  valid: boolean;
  status: string;
  certificate_number: string;
  organization: string | null;
  hai_score: number | null;
  signed_at: string | null;
  expires_at: string | null;
  reviewer: string | null;
  methodology_version: string | null;
}

export interface Benchmark {
  industry: string;
  stage_band: string;
  size_band: string;
  organizations: number;
  average_score: number | null;
  average_confidence: number | null;
}

export interface OntologySummary {
  ontology_version: string;
  methodology_version: string;
  methodology_status: string;
  ruleset_version: string;
  manifest_hash: string;
  title: string;
  layers: { code: string; title: string; description: string }[];
  entities: { name: string; table: string; layer: string; mutability: string; fields: number }[];
  vocabularies: string[];
  criteria: string[];
  pillars: string[];
  integrity_constraints: string[];
}

// ---- accounts (services/api/src/hai_api/routers/accounts.py)

export type AccountKind = "platform" | "organization";

export interface Account {
  id: string;
  kind: AccountKind;
  name: string;
  org_id: string | null;
  email_domain: string | null;
  created_at: string;
}

export interface AccountSummary extends Account {
  active_users: number;
  pending_invitations: number;
  api_keys: number;
}

export interface User {
  id: string;
  account_id: string;
  email: string;
  name: string;
  role: string;
  role_label: string;
  scopes: string[];
  industries: string[];
  status: "active" | "disabled";
  created_at: string;
  last_login_at: string | null;
  invited_by: string | null;
}

export interface TeamUser extends User {
  account: Account;
}

export interface RoleCatalog {
  roles: { code: string; label: string; description: string; account_kind: AccountKind; scopes: string[]; narrowable: boolean }[];
  scopes: { code: string; label: string; description: string }[];
}

export interface Me {
  principal: {
    kind: string;
    id: string;
    name: string;
    actor: string;
    scopes: string[];
    is_reviewer: boolean;
    is_platform_admin: boolean;
    manages_team: boolean;
    restricted_to_organizations: string[];
    restricted_to_industries: string[];
  };
  user: User | null;
  account: Account | null;
  session_id: string | null;
  roles: RoleCatalog;
}

export interface LoginResponse {
  token: string;
  token_type: string;
  expires_at: string;
  me: Me;
}

export interface Invitation {
  id: string;
  kind: "invite" | "password_reset";
  account_id: string;
  user_id: string | null;
  email: string;
  role: string;
  role_label: string;
  scopes: string[];
  industries: string[];
  invited_by: string;
  invited_by_name: string | null;
  message: string | null;
  status: "pending" | "accepted" | "revoked" | "expired";
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface InvitationWithLink extends Invitation {
  token: string;
  invite_path: string;
  invite_url: string;
  account: Account;
  domain_match?: boolean;
}

export interface AccessRequest {
  id: string;
  email: string;
  name: string;
  organization_name: string;
  website: string | null;
  message: string | null;
  status: "pending" | "invited" | "dismissed";
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
}

export interface SessionInfo {
  id: string;
  created_at: string;
  expires_at: string;
  last_seen_at: string | null;
  user_agent: string | null;
  current: boolean;
}

export interface ApiKey {
  id: string;
  key_id: string;
  name: string;
  scopes: string[];
  created_by: string;
  account_id: string | null;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  status: "active" | "revoked";
}

const BASE: string = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...authHeaders(), ...extraHeaders };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const response = await fetch(BASE + path, { method, headers, body: payload });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const data = text ? (JSON.parse(text) as unknown) : null;
  if (!response.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | null)?.error;
    // A session the server no longer accepts (signed out elsewhere, disabled, expired) is dropped here;
    // the auth gate then shows the sign-in page. Sign-in itself is excluded so a wrong password stays an error.
    if (response.status === 401 && readCredentials().session && !path.startsWith("/v1/auth/login")) dropSession();
    throw new ApiRequestError(response.status, err?.code ?? "http_error", err?.message ?? response.statusText, err?.details ?? {});
  }
  return data as T;
}

export const api = {
  health: () => request<{ status: string; ontology_version: string; methodology_version: string }>("GET", "/health"),
  ready: () => request<{ status: string }>("GET", "/ready"),
  listAssessments: (params: { limit?: number; offset?: number; org_id?: string } = {}) =>
    request<Page<Assessment>>("GET", "/v1/assessments?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))),
  getAssessment: (id: string) => request<Assessment>("GET", `/v1/assessments/${id}`),
  createAssessment: (body: Record<string, unknown>, idempotencyKey: string) => request<Assessment>("POST", "/v1/assessments", body, { "Idempotency-Key": idempotencyKey }),
  cancelAssessment: (id: string) => request<Assessment>("POST", `/v1/assessments/${id}/cancel`),
  reassess: (id: string) => request<Assessment>("POST", `/v1/assessments/${id}/reassess`),
  requestCertification: (id: string) => request<Assessment>("POST", `/v1/assessments/${id}/certification-request`),
  getResult: (id: string) => request<Result>("GET", `/v1/assessments/${id}/result`),
  getReport: (id: string) => request<Report>("GET", `/v1/assessments/${id}/report`),
  getDecisions: (id: string) => request<Page<Decision>>("GET", `/v1/assessments/${id}/decisions`),
  getTrace: (id: string) => request<Trace>("GET", `/v1/assessments/${id}/trace`),
  getCriterionTrace: (id: string, code: string) => request<Trace>("GET", `/v1/assessments/${id}/trace/${code}`),
  getConnectorRuns: (id: string) => request<Page<ConnectorRun>>("GET", `/v1/assessments/${id}/connector-runs`),
  listTasks: (params: { status?: string; assessment_id?: string } = {}) =>
    request<Page<ReviewTask>>("GET", "/v1/reviews/tasks?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))),
  review: (body: { task_id: string; action: string; reason: string }) => request<{ review: Record<string, unknown>; task: ReviewTask; finalize_queued: boolean }>("POST", "/v1/reviews", body),
  signCertification: (id: string, body: { decision: string; reason: string }) => request<Record<string, unknown>>("POST", `/v1/assessments/${id}/certification`, body),
  verifyCertificate: (number: string) => request<Verification>("GET", `/v1/certifications/${encodeURIComponent(number)}/verify`),
  listOrganizations: (q?: string) => request<Page<Organization>>("GET", "/v1/organizations" + (q ? `?q=${encodeURIComponent(q)}` : "")),
  getOrganization: (id: string) => request<Organization>("GET", `/v1/organizations/${id}`),
  orgAssessments: (id: string) => request<Page<Assessment>>("GET", `/v1/organizations/${id}/assessments`),
  orgEvidence: (id: string, params: { limit?: number; offset?: number; criterion?: string } = {}) =>
    request<Page<EvidenceItem & { criterion_code: string; publisher: string; canonical_url: string }>>("GET", `/v1/organizations/${id}/evidence?` + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))),
  benchmarks: () => request<Page<Benchmark>>("GET", "/v1/benchmarks/industries"),
  ontology: () => request<OntologySummary>("GET", "/v1/ontology"),
  entity: (name: string) => request<Record<string, unknown>>("GET", `/v1/ontology/entities/${name}`),
  vocabulary: (code: string) => request<{ code: string; title: string; description: string; values: { code: string; label: string; description: string; attributes?: Record<string, unknown> }[] }>("GET", `/v1/ontology/vocabularies/${code}`),
  integrityConstraints: () => request<Page<{ id: string; rule: string; enforced_in: string; implementation: string; acceptance_test: string }>>("GET", "/v1/ontology/integrity-constraints"),
  criteria: () => request<Page<Record<string, unknown>>>("GET", "/v1/methodology/criteria"),
  // accounts
  authStatus: () => request<{ bootstrapped: boolean; signup: string; platform_name: string }>("GET", "/v1/auth/status"),
  login: (body: { email: string; password: string; remember_me: boolean }) => request<LoginResponse>("POST", "/v1/auth/login", body),
  bootstrap: (body: { email: string; name: string; password: string; platform_name: string }) => request<LoginResponse>("POST", "/v1/auth/bootstrap", body),
  logout: (everywhere = false) => request<void>("POST", `/v1/auth/logout${everywhere ? "?everywhere=true" : ""}`),
  me: () => request<Me>("GET", "/v1/auth/me"),
  updateMe: (body: { name: string }) => request<Me>("PATCH", "/v1/auth/me", body),
  changePassword: (body: { current_password: string; new_password: string }) => request<void>("POST", "/v1/auth/password", body),
  mySessions: () => request<Page<SessionInfo>>("GET", "/v1/auth/sessions"),
  invitationByToken: (token: string) => request<Invitation & { account: Account }>("GET", `/v1/auth/invitations/${encodeURIComponent(token)}`),
  register: (body: { token: string; name: string; password: string }) => request<LoginResponse>("POST", "/v1/auth/register", body),
  requestAccess: (body: { email: string; name: string; organization_name: string; website?: string; message?: string }) =>
    request<{ id: string; status: string; created_at: string }>("POST", "/v1/auth/access-requests", body),
  // team
  teamRoles: () => request<RoleCatalog>("GET", "/v1/team/roles"),
  teamUsers: () => request<Page<TeamUser>>("GET", "/v1/team/users"),
  updateUser: (id: string, body: { name?: string; role?: string; scopes?: string[]; industries?: string[]; status?: "active" | "disabled" }) =>
    request<TeamUser>("PATCH", `/v1/team/users/${id}`, body),
  resetLink: (id: string) => request<InvitationWithLink>("POST", `/v1/team/users/${id}/reset-link`),
  teamInvitations: () => request<Page<Invitation & { account: Account }>>("GET", "/v1/team/invitations"),
  invite: (body: { email: string; role: string; org_id?: string; industries?: string[]; scopes?: string[]; message?: string }) =>
    request<InvitationWithLink>("POST", "/v1/team/invitations", body),
  revokeInvitation: (id: string) => request<void>("DELETE", `/v1/team/invitations/${id}`),
  teamAccounts: () => request<Page<AccountSummary>>("GET", "/v1/team/accounts"),
  accessRequests: (status: "pending" | "all" = "pending") => request<Page<AccessRequest>>("GET", `/v1/team/access-requests?status=${status}`),
  dismissAccessRequest: (id: string) => request<AccessRequest>("POST", `/v1/team/access-requests/${id}/dismiss`),
  // API keys
  apiKeys: () => request<Page<ApiKey>>("GET", "/v1/api-keys"),
  createApiKey: (body: { name: string; scopes?: string[] }) => request<ApiKey & { api_key: string }>("POST", "/v1/api-keys", body),
  revokeApiKey: (keyId: string) => request<void>("DELETE", `/v1/api-keys/${encodeURIComponent(keyId)}`),
};

export function idempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
