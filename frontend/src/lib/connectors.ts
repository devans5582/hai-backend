// Display metadata for connectors. The code list must match config/connectors.yaml; a contract test checks it.
export const CONNECTORS: Record<string, { label: string; description: string }> = {
  WEBSITE: { label: "Organization website", description: "Governance pages on the organization's own site" },
  DIRECT_URL: { label: "Supplied URLs", description: "Governance pages supplied with the request" },
  EDGAR: { label: "SEC EDGAR", description: "Regulatory filings matched to the filer" },
  NEWS: { label: "News", description: "Press coverage with real dates and publishers" },
  GITHUB: { label: "GitHub", description: "Repositories of the verified organization handle" },
  ACADEMIC: { label: "Research", description: "Papers that concern the organization" },
  WAYBACK: { label: "Web archive", description: "Archived copies of governance pages" },
  UPLOAD: { label: "Evidence portal", description: "Documents submitted by the organization (claims)" },
  ISO_42001: { label: "ISO/IEC 42001 registry", description: "Certificate registry lookup" },
};

export const CONNECTOR_CODES = Object.keys(CONNECTORS);

export function connectorLabel(code: string): string {
  return CONNECTORS[code]?.label ?? code;
}
