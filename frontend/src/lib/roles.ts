// Console roles. These describe who may use the console, not what is scored, so they are not
// part of the ontology. Labels normally come from the API role catalog; these are fallbacks.
export const PLATFORM_ROLES = ["owner", "admin", "reviewer", "analyst", "viewer"] as const;
export const ORGANIZATION_ROLES = ["org_admin", "org_member"] as const;
export type PlatformRole = (typeof PLATFORM_ROLES)[number];
export type OrganizationRole = (typeof ORGANIZATION_ROLES)[number];
export type Role = PlatformRole | OrganizationRole;

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Platform owner",
  admin: "Administrator",
  reviewer: "Reviewer",
  analyst: "Analyst",
  viewer: "Viewer",
  org_admin: "Organization admin",
  org_member: "Organization member",
};

export function roleLabel(role: string | null | undefined, catalog?: { code: string; label: string }[]): string {
  if (!role) return "";
  return catalog?.find((r) => r.code === role)?.label ?? ROLE_LABELS[role as Role] ?? role;
}

export const SCOPES = {
  assessmentsRead: "assessments:read",
  assessmentsWrite: "assessments:write",
  organizationsRead: "organizations:read",
  reviewsWrite: "reviews:write",
  certificationSign: "certification:sign",
  uploadsWrite: "uploads:write",
  webhooksWrite: "webhooks:write",
  auditRead: "audit:read",
  ontologyRead: "ontology:read",
  admin: "admin",
} as const;

export function hasScope(scopes: readonly string[] | undefined, scope: string): boolean {
  if (!scopes) return false;
  return scopes.includes(SCOPES.admin) || scopes.includes(scope);
}
