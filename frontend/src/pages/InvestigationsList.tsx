import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useInvestigations } from "../api/queries";
import { PageHeader } from "../components/PageHeader";
import { INVESTIGATION_STATUS_LABELS, INVESTIGATION_TYPE_LABELS } from "../api/types";
import type { InvestigationStatus } from "../api/types";

const STATUS_OPTIONS = Object.keys(INVESTIGATION_STATUS_LABELS) as InvestigationStatus[];

export function InvestigationsList() {
  const [status, setStatus] = useState<string>("");
  const { data, isLoading, isError } = useInvestigations({ status: status || undefined });
  const navigate = useNavigate();

  return (
    <div>
      <PageHeader
        title="Investigations"
        description="Nonconforming-work CAPA tracking (ISO/IEC 17025:2017 7.10)."
        actions={
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="btn" aria-label="Filter by status">
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {INVESTIGATION_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        }
      />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load investigations.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">No investigations match this filter.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Related to</th>
                <th>Type</th>
                <th>Status</th>
                <th>Opened by</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((inv) => (
                <tr key={inv.id} onClick={() => navigate(`/investigations/${inv.id}`)}>
                  <td style={{ fontWeight: 600 }}>
                    {inv.related_sample_code || (inv.related_test_result ? `Test Result #${inv.related_test_result}` : "—")}
                  </td>
                  <td>{INVESTIGATION_TYPE_LABELS[inv.type]}</td>
                  <td>{INVESTIGATION_STATUS_LABELS[inv.status]}</td>
                  <td>{inv.opened_by_display_name}</td>
                  <td>{new Date(inv.opened_at).toLocaleDateString()}</td>
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
