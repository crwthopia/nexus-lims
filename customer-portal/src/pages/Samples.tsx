import { useMySamples } from "../api/queries";
import { SAMPLE_STATUS_LABELS } from "../api/types";

export function Samples() {
  const { data, isLoading, isError } = useMySamples();

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>My Samples</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>Track your samples through testing.</p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load your samples.</div>}
        {data && data.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No samples yet.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Sample code</th>
                <th>Service line</th>
                <th>Status</th>
                <th>Client reference</th>
                <th>Submitted</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((s) => (
                <tr key={s.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>{s.unique_sample_code}</td>
                  <td>{s.service_line.replace("_", " ")}</td>
                  <td>{SAMPLE_STATUS_LABELS[s.status]}</td>
                  <td>{s.client_reference || "—"}</td>
                  <td>{new Date(s.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
