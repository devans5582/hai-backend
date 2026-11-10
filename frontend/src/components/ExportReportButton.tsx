import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, saveDownload } from "../lib/api";
import { Icon } from "./Icon";

type Target = { assessmentId: string; organizationId?: never } | { organizationId: string; assessmentId?: never };

type Props = Target & {
  /** What the file is, for the accessible name: "Acme Corp", "version 2 of Acme Corp". */
  subject: string;
  /** A compact icon-only button for table rows. */
  compact?: boolean;
  /** Visual weight of the full button. */
  primary?: boolean;
};

/**
 * Downloads the PDF rendering of a report. The API renders it from the same stored values the
 * JSON report returns; the console only hands the file to the browser.
 */
export function ExportReportButton({ subject, compact = false, primary = false, ...target }: Props) {
  const [done, setDone] = useState(false);
  const exportPdf = useMutation({
    mutationFn: () =>
      target.assessmentId !== undefined ? api.downloadReportPdf(target.assessmentId) : api.downloadOrganizationReportPdf(target.organizationId),
    onSuccess: (file) => {
      saveDownload(file);
      setDone(true);
    },
  });
  useEffect(() => {
    if (!done) return;
    const timer = setTimeout(() => setDone(false), 2500);
    return () => clearTimeout(timer);
  }, [done]);
  const pending = exportPdf.isPending;
  const label = pending ? "Preparing PDF…" : done ? "PDF downloaded" : "Export PDF";
  const accessible = `${label}: report for ${subject}`;
  const message = exportPdf.error ? (exportPdf.error as Error).message : null;
  if (compact) {
    return (
      <button
        type="button"
        className={`icon-button table-row-action export-compact ${pending ? "is-pending" : ""}`}
        onClick={() => exportPdf.mutate()}
        disabled={pending}
        aria-label={accessible}
        title={message ? `Export failed: ${message}` : "Export the report as PDF"}
        aria-busy={pending}
      >
        <Icon name={done ? "check" : exportPdf.error ? "alert-triangle" : "download"} />
      </button>
    );
  }
  return (
    <span className="export-report">
      <button type="button" className={primary ? "primary" : ""} onClick={() => exportPdf.mutate()} disabled={pending} aria-busy={pending} aria-label={accessible}>
        <Icon name={done ? "check" : "download"} /> {label}
      </button>
      {message && (
        <span className="export-error small" role="alert">
          Export failed: {message}
        </span>
      )}
    </span>
  );
}
