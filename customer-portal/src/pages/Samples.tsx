import { useMySamples } from "../api/queries";
import { SAMPLE_STATUS_LABELS } from "../api/types";
import { PageHeader } from "../components/PageHeader";

export function Samples() {
  const { data, isLoading, isError } = useMySamples();

  return (
    <div>
      <PageHeader title="My Samples" description="Track your samples through testing." />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load your samples.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">No samples yet.</div>
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
