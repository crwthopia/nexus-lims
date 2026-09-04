import { useState } from "react";
import { useParams } from "react-router-dom";
import { useCreateEnrollment, useEnrollmentAction, useEnrollmentsForSession, useTrainingSession, useTrainingSessionAction } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { ENROLLMENT_STATUS_LABELS, TRAINING_SESSION_ACTIONS_BY_STATUS, TRAINING_SESSION_STATUS_LABELS, TRAINING_WRITE_ROLES } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const SESSION_ACTION_LABELS: Record<string, string> = {
  "start-session": "Start Session",
  "complete-session": "Complete Session",
  "cancel-session": "Cancel Session",
};

const DESTRUCTIVE_ACTIONS = new Set(["cancel-session"]);

export function TrainingSessionDetail() {
  const { id } = useParams<{ id: string }>();
  const sessionId = Number(id);
  const { data: session, isLoading, isError } = useTrainingSession(sessionId);
  const { data: enrollments } = useEnrollmentsForSession(sessionId);
  const { hasRole } = useAuth();
  const canWrite = hasRole(...TRAINING_WRITE_ROLES);
  const sessionAction = useTrainingSessionAction(sessionId);
  const enrollmentAction = useEnrollmentAction(sessionId);
  const createEnrollment = useCreateEnrollment(sessionId);

  const [customerId, setCustomerId] = useState("");

  if (isLoading) return <div>Loading…</div>;
  if (isError || !session) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this session.</div>;

  const availableActions = TRAINING_SESSION_ACTIONS_BY_STATUS[session.status] ?? [];

  function submitEnrollment(e: React.FormEvent) {
    e.preventDefault();
    createEnrollment.mutate({ customer: Number(customerId) }, { onSuccess: () => setCustomerId("") });
  }

  return (
    <div>
      <PageHeader
        back={{ to: "/training", label: "training" }}
        title={session.course_title}
        meta={
          <span className="badge badge-neutral">
            {TRAINING_SESSION_STATUS_LABELS[session.status]}
          </span>
        }
      />

      <div className="detail-grid">
        <div className="stack">
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Details</h2>
            <dl className="field-grid">
              <Field label="Start" value={new Date(session.start_date).toLocaleString()} />
              <Field label="End" value={new Date(session.end_date).toLocaleString()} />
              <Field label="Capacity" value={`${session.confirmed_enrollment_count} / ${session.capacity}`} />
              <Field label="Minimum capacity" value={String(session.min_capacity)} />
              <Field label="Instructor" value={session.instructor_display_name || "—"} />
              <Field label="Cancellation threshold" value={`${session.cancellation_threshold_days} days before start`} />
            </dl>
            <a
              href={`/api/v1/training-sessions/${sessionId}/attendee-export/`}
              className="btn"
              style={{ display: "inline-flex" }}
            >
              Download attendee export (CSV)
            </a>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Enrollments</h2>
            {!enrollments || enrollments.results.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No enrollments yet.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Status</th>
                    <th>Payment</th>
                    <th>Certificate</th>
                    {canWrite && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {enrollments.results.map((e) => (
                    <tr key={e.id} style={{ cursor: "default" }}>
                      <td>{e.customer_email}</td>
                      <td>{ENROLLMENT_STATUS_LABELS[e.status]}</td>
                      <td style={{ textTransform: "capitalize" }}>{e.payment_status.replace("_", " ")}</td>
                      <td>{e.certificate_issued ? "Issued" : "—"}</td>
                      {canWrite && (
                        <td style={{ display: "flex", gap: 6 }}>
                          {e.status === "confirmed" && (
                            <>
                              <button
                                className="btn btn-primary"
                                disabled={enrollmentAction.isPending}
                                onClick={() => enrollmentAction.mutate({ enrollmentId: e.id, action: "complete" })}
                              >
                                Complete
                              </button>
                              <button
                                className="btn btn-danger"
                                disabled={enrollmentAction.isPending}
                                onClick={() => enrollmentAction.mutate({ enrollmentId: e.id, action: "cancel" })}
                              >
                                Cancel
                              </button>
                            </>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {enrollmentAction.isError && (
              <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>
                {describeApiError(enrollmentAction.error)}
              </p>
            )}

            {canWrite && (
              <form onSubmit={submitEnrollment} style={{ display: "flex", gap: 8, marginTop: 16, alignItems: "flex-end" }}>
                <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
                  Register walk-in (customer ID)
                  <input
                    type="number"
                    value={customerId}
                    onChange={(e) => setCustomerId(e.target.value)}
                    required
                  />
                </label>
                <button type="submit" className="btn btn-primary" disabled={createEnrollment.isPending}>
                  Enroll
                </button>
              </form>
            )}
            {createEnrollment.isError && (
              <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 8 }}>
                {describeApiError(createEnrollment.error)}
              </p>
            )}
          </div>
        </div>

        <div className="card" style={{ padding: 20, alignSelf: "start" }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Actions</h2>
          {availableActions.length === 0 && (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No further actions from this status.</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {availableActions.map((name) => (
              <button
                key={name}
                className={`btn ${DESTRUCTIVE_ACTIONS.has(name) ? "btn-danger" : "btn-primary"}`}
                disabled={!canWrite || sessionAction.isPending}
                title={canWrite ? undefined : `Requires role: ${TRAINING_WRITE_ROLES.join(" or ")}`}
                onClick={() => sessionAction.mutate(name)}
              >
                {SESSION_ACTION_LABELS[name] ?? name}
              </button>
            ))}
          </div>
          {sessionAction.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>
              {describeApiError(sessionAction.error)}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>{label}</dt>
      <dd style={{ margin: "0 0 10px" }}>{value}</dd>
    </>
  );
}

