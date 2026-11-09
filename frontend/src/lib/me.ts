// Who is signed in, as the API describes it. The console never derives permissions on its own:
// it asks /v1/auth/me and renders what comes back.
import { useQuery } from "@tanstack/react-query";
import { api, type Me } from "./api";
import { useAuth } from "./auth";
import { hasScope, SCOPES } from "./roles";

export interface Capabilities {
  viewAssessments: boolean;
  startAssessments: boolean;
  reviewQueue: boolean;
  signCertifications: boolean;
  manageTeam: boolean;
  platformAdmin: boolean;
  auditLog: boolean;
  organizationAccount: boolean;
}

export function capabilitiesOf(me: Me | undefined): Capabilities {
  const scopes = me?.principal.scopes;
  return {
    viewAssessments: hasScope(scopes, SCOPES.assessmentsRead),
    startAssessments: hasScope(scopes, SCOPES.assessmentsWrite),
    reviewQueue: hasScope(scopes, SCOPES.reviewsWrite) && !!me?.principal.is_reviewer,
    signCertifications: hasScope(scopes, SCOPES.certificationSign) && !!me?.principal.is_reviewer,
    manageTeam: !!me?.principal.manages_team,
    platformAdmin: !!me?.principal.is_platform_admin,
    auditLog: hasScope(scopes, SCOPES.auditRead),
    organizationAccount: me?.account?.kind === "organization",
  };
}

export function useMe() {
  const { session, apiKey, reviewerToken, mode } = useAuth();
  const query = useQuery({
    queryKey: ["me", session ?? reviewerToken ?? apiKey ?? "anonymous"],
    queryFn: api.me,
    enabled: mode !== "none",
    staleTime: 60_000,
    retry: false,
  });
  return { ...query, me: query.data, capabilities: capabilitiesOf(query.data), mode };
}
