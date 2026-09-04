import { Link } from "react-router-dom";
import { useEnrollInSession, useTrainingCourses, useTrainingSessions } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { TRAINING_SESSION_STATUS_LABELS } from "../api/types";
import { PageHeader } from "../components/PageHeader";

/** Public per the backend (AllowAny) -- Blueprint 4.3: customers browse the catalog before necessarily having an account. */
export function TrainingCatalog() {
  const { isAuthenticated } = useAuth();
  const { data: courses } = useTrainingCourses();
  const { data: sessions, isLoading, isError } = useTrainingSessions();
  const enroll = useEnrollInSession();

  const courseTitleById = new Map(courses?.results.map((c) => [c.id, c.title]));

  return (
    <div>
      <PageHeader title="Training" description="CPD-accredited technical trainings and workshops." />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load the training catalog.</div>}
        {sessions && sessions.results.length === 0 && (
          <div className="card-state">No sessions scheduled right now.</div>
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
