import { useNavigate } from "react-router-dom";
import { useTestRequestQueue } from "../api/queries";
import { PageHeader } from "../components/PageHeader";
import {
  DUE_BASIS_LABELS,
  SAMPLE_PRIORITY_LABELS,
  TEST_REQUEST_STATUS_LABELS,
} from "../api/types";
import type { TestRequest } from "../api/types";

/**
 * TestRequests in assigned/in_progress -- what an Analyst has queued up or
 * is actively working. status query supports comma-separated values (see
 * TestRequestViewSet.get_queryset, apps/testing/views.py) so this is one
 * request rather than merging two lists client-side.
 *
 * The server returns these in _QUEUE_ORDER -- priority, then holding-time
 * deadline, then creation -- so this table is read top-down as "what to do
 * next" rather than as a list of what was booked in. Nothing here re-sorts;
 * a client that imposed its own order would quietly disagree with the sweep
 * that chases the same deadlines.
 */
export function TestingQueue() {
  const { data, isLoading, isError } = useTestRequestQueue(["assigned", "in_progress"]);
  const navigate = useNavigate();

  const overdueCount = data?.results.filter((tr) => tr.is_overdue).length ?? 0;

  return (
    <div>
      <PageHeader
        title="Testing Queue"
        description="Test requests assigned or in progress, most urgent first."
      />

      {overdueCount > 0 && (
        <div
          className="card"
          style={{
            padding: "12px 16px",
            marginBottom: 12,
            border: "1px solid var(--color-danger)",
            background: "var(--color-danger-bg)",
            color: "var(--color-danger)",
            fontSize: "0.9rem",
          }}
        >
          <strong>
            {overdueCount} {overdueCount === 1 ? "analysis is" : "analyses are"} past the holding time.
          </strong>{" "}
          A result produced outside its holding time is nonconforming work and needs an
          investigation (ISO/IEC 17025:2017 7.4.1, 7.10).
        </div>
      )}

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load the queue.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">Nothing queued up right now.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Sample</th>
                <th>Test method</th>
                <th>Due</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Assigned analyst</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((tr) => (
                <tr key={tr.id} onClick={() => navigate(`/test-requests/${tr.id}`)}>
                  <td style={{ fontWeight: 600 }}>{tr.sample_code}</td>
                  <td>{tr.test_method_name}</td>
                  <td>
                    <DueCell request={tr} />
                  </td>
                  <td>
                    {tr.sample_priority === "routine" ? (
                      <span style={{ color: "var(--color-text-muted)" }}>
                        {SAMPLE_PRIORITY_LABELS.routine}
                      </span>
                    ) : (
                      <strong>{SAMPLE_PRIORITY_LABELS[tr.sample_priority]}</strong>
                    )}
                  </td>
                  <td>{TEST_REQUEST_STATUS_LABELS[tr.status]}</td>
                  <td>{tr.assigned_analyst_display_name || "Unassigned"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && (
        <div style={{ marginTop: 12, color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
          {data.count} queued
        </div>
      )}
    </div>
  );
}

/**
 * The deadline, and how much of it is left.
 *
 * An em dash rather than a blank for the no-deadline case: plenty of
 * methods carry no holding time at all, and an empty cell reads as missing
 * data rather than as "nothing expires here".
 *
 * The basis is shown because it changes what the date means. A deadline
 * counted from receipt is optimistic -- the sample's real clock started
 * when it was taken, which nobody recorded -- and an analyst deciding what
 * to run next should be able to see which of the two they are looking at.
 */
function DueCell({ request }: { request: TestRequest }) {
  if (!request.due_at) {
    return <span style={{ color: "var(--color-text-muted)" }}>—</span>;
  }

  const due = new Date(request.due_at);
  const basis = request.due_at_basis ? DUE_BASIS_LABELS[request.due_at_basis] : null;

  return (
    <span style={request.is_overdue ? { color: "var(--color-danger)", fontWeight: 600 } : undefined}>
      {due.toLocaleString()}
      {request.is_overdue && " · overdue"}
      {basis && (
        <span style={{ display: "block", color: "var(--color-text-muted)", fontSize: "0.8rem", fontWeight: 400 }}>
          {basis}
        </span>
      )}
    </span>
  );
}
