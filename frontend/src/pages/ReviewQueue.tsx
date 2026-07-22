import { useNavigate } from "react-router-dom";
import { useSamples } from "../api/queries";

/**
 * Samples sitting in under_review, for Reviewer/Approver/QA Officer/Lab
 * Supervisor to work from -- a purpose-built worklist rather than making
 * people filter the full Samples list by hand every time. Segregation of
 * duties (water_environmental: approver != reviewer, ASTM E1578-18 6.6.1)
 * is still enforced server-side and surfaced per-sample on the detail page
 * (apps/review/services.py check_can_approve) -- this queue doesn't need to
 * duplicate that logic, just get people to the right samples.
 */
export function ReviewQueue() {
  const { data, isLoading, isError } = useSamples({ status: "under_review" });
  const navigate = useNavigate();

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>Review Queue</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
          Samples awaiting review or approval.
        </p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load the queue.</div>}
        {data && data.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>
            Nothing waiting on review right now.
          </div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Sample code</th>
                <th>Service line</th>
                <th>Client reference</th>
                <th>Entered review</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((sample) => (
                <tr key={sample.id} onClick={() => navigate(`/samples/${sample.id}`)}>
                  <td style={{ fontWeight: 600 }}>{sample.unique_sample_code}</td>
                  <td style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {sample.service_line.replace("_", " ")}
                    {sample.service_line === "water_environmental" && (
                      <span
                        className="badge"
                        style={{ background: "var(--color-warning-bg)", color: "var(--color-warning)" }}
                        title="Regulated service line: the Approver must differ from the Reviewer (ASTM E1578-18 6.6.1)."
                      >
                        Regulated
                      </span>
                    )}
                  </td>
                  <td>{sample.client_reference || "—"}</td>
                  <td>{new Date(sample.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && <div style={{ marginTop: 12, color: "var(--color-text-muted)", fontSize: "0.85rem" }}>{data.count} awaiting review</div>}
    </div>
  );
}
