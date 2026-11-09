import { fmtDate, fmtDateTime } from "../lib/format";

export function TableDate({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="table-placeholder">—</span>;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return <span>{value}</span>;
  return (
    <time className="table-date" dateTime={value} title={fmtDateTime(value)}>
      <span>{fmtDate(value)}</span>
      <small>{date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</small>
    </time>
  );
}
