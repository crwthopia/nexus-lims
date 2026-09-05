import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSamples } from "../api/queries";
import { StatusBadge } from "../components/StatusBadge";
import { PageHeader } from "../components/PageHeader";
import type { SampleStatus } from "../api/types";
import { SAMPLE_STATUS_LABELS } from "../api/types";

const STATUS_OPTIONS = Object.keys(SAMPLE_STATUS_LABELS) as SampleStatus[];

export function SamplesList() {
  const [status, setStatus] = useState<string>("");
  const { data, isLoading, isError } = useSamples({ status: status || undefined });
  const navigate = useNavigate();

  return (
    <div>
      <PageHeader
        title="Samples"
        description="Every sample the lab has received, newest first."
        actions={
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="btn" aria-label="Filter by status">
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {SAMPLE_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        }
      />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading samples…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load samples.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">No samples match this filter.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Sample code</th>
                <th>Service line</th>
                <th>Status</th>
                <th>Client reference</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((sample) => (
                <tr key={sample.id} onClick={() => navigate(`/samples/${sample.id}`)}>
                  <td style={{ fontWeight: 600 }}>{sample.unique_sample_code}</td>
                  <td>{sample.service_line.replace("_", " ")}</td>
                  <td>
                    <StatusBadge status={sample.status} />
                  </td>
                  <td>{sample.client_reference || "—"}</td>
                  <td>{new Date(sample.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && <div style={{ marginTop: 12, color: "var(--color-text-muted)", fontSize: "0.85rem" }}>{data.count} total</div>}
    </div>
  );
}
