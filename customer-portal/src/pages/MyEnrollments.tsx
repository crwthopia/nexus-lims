import { useMyEnrollments, useTrainingSessions } from "../api/queries";
import { ENROLLMENT_STATUS_LABELS } from "../api/types";
import { PageHeader } from "../components/PageHeader";

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
      <PageHeader title="My Enrollments" description="Trainings you've registered for." />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load your enrollments.</div>}
        {enrollments && enrollments.results.length === 0 && (
          <div className="card-state">No enrollments yet.</div>
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
