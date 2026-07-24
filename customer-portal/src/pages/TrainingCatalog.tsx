import { Link } from "react-router-dom";
import { useEnrollInSession, useTrainingCourses, useTrainingSessions } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { describeApiError } from "../api/client";
import { TRAINING_SESSION_STATUS_LABELS } from "../api/types";

/** Public per the backend (AllowAny) -- Blueprint 4.3: customers browse the catalog before necessarily having an account. */
export function TrainingCatalog() {
  const { isAuthenticated } = useAuth();
  const { data: courses } = useTrainingCourses();
  const { data: sessions, isLoading, isError } = useTrainingSessions();
  const enroll = useEnrollInSession();

  const courseTitleById = new Map(courses?.results.map((c) => [c.id, c.title]));

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>Training</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
          CPD-accredited technical trainings and workshops.
        </p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load the training catalog.</div>}
        {sessions && sessions.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No sessions scheduled right now.</div>
        )}
        {sessions && sessions.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Course</th>
                <th>Start</th>
                <th>Status</th>
                <th>Seats</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sessions.results.map((s) => {
                const isFull = s.confirmed_enrollment_count >= s.capacity;
                const isOpen = s.status === "scheduled" && !isFull;
                return (
                  <tr key={s.id} style={{ cursor: "default" }}>
                    <td style={{ fontWeight: 600 }}>{courseTitleById.get(s.course) ?? s.course_title}</td>
                    <td>{new Date(s.start_date).toLocaleString()}</td>
                    <td>{TRAINING_SESSION_STATUS_LABELS[s.status]}</td>
                    <td>
                      {s.confirmed_enrollment_count} / {s.capacity}
                    </td>
                    <td>
                      {!isAuthenticated ? (
                        <Link to="/login" className="btn" style={{ fontSize: "0.85rem" }}>
                          Log in to enroll
                        </Link>
                      ) : isOpen ? (
                        <button className="btn btn-primary" disabled={enroll.isPending} onClick={() => enroll.mutate(s.id)}>
                          Enroll
                        </button>
                      ) : (
                        <span style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                          {isFull ? "Full" : "Not open"}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {enroll.isError && (
        <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>{describeApiError(enroll.error)}</p>
      )}
      {enroll.isSuccess && (
        <p style={{ color: "var(--color-success)", fontSize: "0.85rem", marginTop: 12 }}>
          Enrolled! See it under <Link to="/my-enrollments">My Enrollments</Link>.
        </p>
      )}
    </div>
  );
}
