/**
 * The system failure register (ISO/IEC 17025:2017 7.11.3(e)).
 *
 * One route rather than list + detail: a failure is a handful of fields and
 * one text box, and the thing an operator actually does here -- read what
 * broke, then write what was done about it -- is worse across two pages.
 *
 * The screen's job beyond display is to make the two halves of the clause
 * visibly different. What the *system* did is shown as a fact and cannot be
 * edited; what a *person* did is an empty box until someone fills it in, and
 * a failure with an empty box cannot be closed. That refusal lives on the
 * server; this screen just declines to pretend otherwise.
 */

import { useState } from "react";
import { describeApiError } from "../api/client";
import {
  useAcknowledgeSystemFailure,
  useCloseSystemFailure,
  useSystemFailures,
} from "../api/queries";
import { useAuth } from "../auth/context";
import {
  SYSTEM_FAILURE_SEVERITY_LABELS,
  SYSTEM_FAILURE_STATUS_LABELS,
  SYSTEM_FAILURE_WRITE_ROLES,
} from "../api/types";
import type { SystemFailure, SystemFailureStatus } from "../api/types";

const STATUS_OPTIONS = Object.keys(SYSTEM_FAILURE_STATUS_LABELS) as SystemFailureStatus[];

function FailurePanel({ failure, canWrite }: { failure: SystemFailure; canWrite: boolean }) {
  const acknowledge = useAcknowledgeSystemFailure(failure.id);
  const close = useCloseSystemFailure(failure.id);
  const [correctiveAction, setCorrectiveAction] = useState(failure.corrective_action);

  const isClosed = failure.status === "closed";
  const error = acknowledge.error ?? close.error;

  return (
    <div className="card" style={{ padding: 20, marginTop: 12 }}>
      <div style={{ display: "grid", gap: 4, marginBottom: 16 }}>
        <div style={{ fontFamily: "monospace", fontSize: "0.85rem", whiteSpace: "pre-wrap" }}>
          {failure.detail || "No further detail was recorded."}
        </div>
      </div>

      <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px", margin: "0 0 20px", fontSize: "0.9rem" }}>
        <dt style={{ color: "var(--color-text-muted)" }}>Immediate action</dt>
        <dd style={{ margin: 0 }}>{failure.immediate_action_display}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>First seen</dt>
        <dd style={{ margin: 0 }}>{new Date(failure.first_seen_at).toLocaleString()}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Last seen</dt>
        <dd style={{ margin: 0 }}>{new Date(failure.last_seen_at).toLocaleString()}</dd>
        {failure.acknowledged_by_display_name && (
          <>
            <dt style={{ color: "var(--color-text-muted)" }}>Acknowledged by</dt>
            <dd style={{ margin: 0 }}>{failure.acknowledged_by_display_name}</dd>
          </>
        )}
        {failure.closed_by_display_name && (
          <>
            <dt style={{ color: "var(--color-text-muted)" }}>Closed by</dt>
            <dd style={{ margin: 0 }}>{failure.closed_by_display_name}</dd>
          </>
        )}
      </dl>

      {isClosed ? (
        <div>
          <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem", marginBottom: 4 }}>Corrective action</div>
          <div style={{ whiteSpace: "pre-wrap" }}>{failure.corrective_action}</div>
        </div>
      ) : canWrite ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            close.mutate(correctiveAction);
          }}
        >
          <label htmlFor={`corrective-action-${failure.id}`} style={{ display: "block", marginBottom: 4, fontSize: "0.85rem" }}>
            Corrective action
          </label>
          <textarea
            id={`corrective-action-${failure.id}`}
            value={correctiveAction}
            onChange={(e) => setCorrectiveAction(e.target.value)}
            rows={3}
            style={{ width: "100%", marginBottom: 4 }}
          />
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", margin: "0 0 12px" }}>
            Required to close (ISO/IEC 17025:2017 7.11.3(e)). If no action was needed, say so and why.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            {failure.status === "open" && (
              <button type="button" className="btn" onClick={() => acknowledge.mutate()} disabled={acknowledge.isPending}>
                Acknowledge
              </button>
            )}
            <button type="submit" className="btn" disabled={close.isPending || !correctiveAction.trim()}>
              Close failure
            </button>
          </div>
        </form>
      ) : (
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem", margin: 0 }}>
          A QA Officer or Lab Supervisor records the corrective action.
        </p>
      )}

      {error && <div style={{ color: "var(--color-danger)", marginTop: 12 }}>{describeApiError(error)}</div>}
    </div>
  );
}

export function SystemFailuresList() {
  // Defaults to the two statuses that are still somebody's problem. A
  // register that opens on "everything ever" buries the four rows that need
  // action under a year of resolved ones.
  const [status, setStatus] = useState<string>("open,acknowledged");
  const [selected, setSelected] = useState<number | null>(null);
  const { data, isLoading, isError } = useSystemFailures({ status: status || undefined });
  const { hasRole } = useAuth();
  const canWrite = hasRole(...SYSTEM_FAILURE_WRITE_ROLES);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>System failures</h1>
          <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
            Failures the system recorded, and what was done about them (ISO/IEC 17025:2017 7.11.3(e)).
          </p>
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="btn"
          style={{ cursor: "pointer" }}
          aria-label="Filter by status"
        >
          <option value="open,acknowledged">Needs attention</option>
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {SYSTEM_FAILURE_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load the failure register.</div>}
        {data && data.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>
            No system failures match this filter.
          </div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Component</th>
                <th>Summary</th>
                <th>Severity</th>
                <th>Occurrences</th>
                <th>Last seen</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((failure) => (
                <tr
                  key={failure.id}
                  onClick={() => setSelected(selected === failure.id ? null : failure.id)}
                  style={{ cursor: "pointer" }}
                >
                  <td style={{ fontWeight: 600 }}>{failure.component_display}</td>
                  <td>{failure.summary}</td>
                  <td>{SYSTEM_FAILURE_SEVERITY_LABELS[failure.severity]}</td>
                  <td>{failure.occurrences}</td>
                  <td>{new Date(failure.last_seen_at).toLocaleString()}</td>
                  <td>{SYSTEM_FAILURE_STATUS_LABELS[failure.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {data?.results
        .filter((failure) => failure.id === selected)
        .map((failure) => <FailurePanel key={failure.id} failure={failure} canWrite={canWrite} />)}

      {data && (
        <div style={{ marginTop: 12, color: "var(--color-text-muted)", fontSize: "0.85rem" }}>{data.count} total</div>
      )}
    </div>
  );
}
