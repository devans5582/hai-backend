import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, QueryState } from "../components/widgets";
import { REVIEW_ACTIONS_BY_SUBJECT, type ReviewAction } from "../generated/ontology";
import { api, ApiRequestError, type ReviewTask } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fmtDateTime, label } from "../lib/format";

export function Reviews() {
  const { reviewer } = useAuth();
  const [status, setStatus] = useState<"open" | "closed" | "all">("open");
  const tasks = useQuery({ queryKey: ["tasks", status], queryFn: () => api.listTasks({ status }) });
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Review queue</h1>
        <div className="row">
          <label htmlFor="status" className="sr-only">
            Task status
          </label>
          <select id="status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)} style={{ width: "auto" }}>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>
      {!reviewer && (
        <div className="alert info">
          Review actions need a reviewer token. Add one on the <Link to="/settings">Settings</Link> page.
        </div>
      )}
      <QueryState isLoading={tasks.isLoading} error={tasks.error}>
        {(tasks.data?.items.length ?? 0) === 0 ? (
          <p className="muted">No tasks.</p>
        ) : (
          <div className="stack">
            {tasks.data?.items.map((t) => <TaskCard key={t.id} task={t} canAct={reviewer} />)}
          </div>
        )}
      </QueryState>
    </div>
  );
}

export function TaskCard({ task, canAct }: { task: ReviewTask; canAct: boolean }) {
  const qc = useQueryClient();
  const allowed: ReviewAction[] = REVIEW_ACTIONS_BY_SUBJECT[task.subject_type] ?? task.allowed_actions;
  const [action, setAction] = useState<string>(allowed[0] ?? "approve");
  const [reason, setReason] = useState("");
  const act = useMutation({ mutationFn: () => api.review({ task_id: task.id, action, reason }), onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }) });
  const err = act.error instanceof ApiRequestError ? act.error : null;
  const open = task.status !== "closed";
  return (
    <article className="card" aria-labelledby={`task-${task.id}`}>
      <div className="row">
        <h2 id={`task-${task.id}`} style={{ margin: 0 }}>
          {label("review_subject_type", task.subject_type)}
        </h2>
        <Badge tone={task.status === "closed" ? "ok" : task.status === "escalated" ? "warn" : "red"}>{task.status}</Badge>
        {task.excluded_reviewers.length > 0 && <span className="small muted">escalated away from {task.excluded_reviewers.join(", ")}</span>}
      </div>
      <p>{task.reason}</p>
      <p className="small muted">
        Opened {fmtDateTime(task.created_at)} by {task.opened_by}
        {task.assessment_id && (
          <>
            {" "}
            for <Link to={`/assessments/${task.assessment_id}`}>assessment {task.assessment_id.slice(0, 8)}</Link>
          </>
        )}
        {task.closed_by ? `. Closed by ${task.closed_by}` : ""}
      </p>
      {open && canAct && (
        <form
          className="row"
          style={{ alignItems: "flex-end" }}
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate();
          }}
        >
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor={`action-${task.id}`}>Action</label>
            <select id={`action-${task.id}`} value={action} onChange={(e) => setAction(e.target.value)} style={{ width: "auto" }}>
              {allowed.map((a) => (
                <option key={a} value={a}>
                  {label("review_action", a)}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ margin: 0, flex: 1, minWidth: 220 }}>
            <label htmlFor={`reason-${task.id}`}>Reason (required)</label>
            <input id={`reason-${task.id}`} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} aria-invalid={!!err} />
          </div>
          <button type="submit" className="primary" disabled={act.isPending || reason.trim().length < 3}>
            Submit
          </button>
        </form>
      )}
      {err && (
        <div className="alert error" role="alert" style={{ marginTop: "0.5rem" }}>
          {err.message}
        </div>
      )}
      {act.data && (
        <div className="alert info" role="status" style={{ marginTop: "0.5rem" }}>
          Recorded. Task is now {act.data.task.status}.{act.data.finalize_queued ? " Finalize queued." : ""}
        </div>
      )}
    </article>
  );
}
