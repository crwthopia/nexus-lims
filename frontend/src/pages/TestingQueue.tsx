import { useNavigate } from "react-router-dom";
import { useTestRequestQueue } from "../api/queries";
import { TEST_REQUEST_STATUS_LABELS } from "../api/types";

/**
 * TestRequests in assigned/in_progress -- what an Analyst has queued up or
 * is actively working. status query supports comma-separated values (see
 * TestRequestViewSet.get_queryset, apps/testing/views.py) so this is one
 * request rather than merging two lists client-side.
 */
export function TestingQueue() {
  const { data, isLoading, isError } = useTestRequestQueue(["assigned", "in_progress"]);
  const navigate = useNavigate();

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>Testing Queue</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
          Test requests assigned or in progress.
        </p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load the queue.</div>}
        {data && data.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>Nothing queued up right now.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Sample</th>
                <th>Test method</th>
                <th>Status</th>
                <th>Assigned analyst</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((tr) => (
                <tr key={tr.id} onClick={() => navigate(`/test-requests/${tr.id}`)}>
                  <td style={{ fontWeight: 600 }}>{tr.sample_code}</td>
                  <td>{tr.test_method_name}</td>
                  <td>{TEST_REQUEST_STATUS_LABELS[tr.status]}</td>
                  <td>{tr.assigned_analyst_display_name || "Unassigned"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && <div style={{ marginTop: 12, color: "var(--color-text-muted)", fontSize: "0.85rem" }}>{data.count} queued</div>}
    </div>
  );
}
