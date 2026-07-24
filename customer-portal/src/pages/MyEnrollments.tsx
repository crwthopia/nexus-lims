import { useMyEnrollments, useTrainingSessions } from "../api/queries";
import { ENROLLMENT_STATUS_LABELS } from "../api/types";

/**
 * CustomerEnrollmentSerializer returns `session` as a bare id (no nested
 * course/date info), so this cross-references the public sessions list to
 * show something more useful than "#4" -- same pattern as the Staff
 * Console needed before its serializers grew display-convenience fields,
 * except here there's no server-side change to make since /training-sessions/
 * already has everything needed.
 */
export function MyEnrollments() {
  const { data: enrollments, isLoading, isError } = useMyEnrollments();
  const { data: sessions } = useTrainingSessions();

  const sessionById = new Map(sessions?.results.map((s) => [s.id, s]));

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>My Enrollments</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>Trainings you've registered for.</p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load your enrollments.</div>}
        {enrollments && enrollments.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No enrollments yet.</div>
        )}
        {enrollments && enrollments.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Course</th>
                <th>Session date</th>
                <th>Status</th>
                <th>Discount</th>
                <th>Payment</th>
                <th>Certificate</th>
              </tr>
            </thead>
            <tbody>
              {enrollments.results.map((e) => {
                const session = sessionById.get(e.session);
                return (
                  <tr key={e.id} style={{ cursor: "default" }}>
                    <td style={{ fontWeight: 600 }}>{session?.course_title ?? `Session #${e.session}`}</td>
                    <td>{session ? new Date(session.start_date).toLocaleDateString() : "—"}</td>
                    <td>{ENROLLMENT_STATUS_LABELS[e.status]}</td>
                    <td>{e.discount_override ?? e.discount_applied}%</td>
                    <td style={{ textTransform: "capitalize" }}>{e.payment_status.replace("_", " ")}</td>
                    <td>{e.certificate_issued ? "Issued" : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
