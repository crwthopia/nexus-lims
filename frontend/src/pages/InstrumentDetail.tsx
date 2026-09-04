import { useState } from "react";
import { useParams } from "react-router-dom";
import { useCalibrationRecordsForInstrument, useCreateCalibrationRecord, useInstrument } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { EQUIPMENT_WRITE_ROLES, INSTRUMENT_MODEL_LABELS, INSTRUMENT_STATUS_LABELS } from "../api/types";
import { PageHeader } from "../components/PageHeader";

export function InstrumentDetail() {
  const { id } = useParams<{ id: string }>();
  const instrumentId = Number(id);
  const { data: instrument, isLoading, isError } = useInstrument(instrumentId);
  const { data: records } = useCalibrationRecordsForInstrument(instrumentId);
  const { hasRole } = useAuth();
  const canWrite = hasRole(...EQUIPMENT_WRITE_ROLES);
  const logCalibration = useCreateCalibrationRecord(instrumentId);

  const [result, setResult] = useState("pass");
  const [nextDueDate, setNextDueDate] = useState("");

  if (isLoading) return <div>Loading…</div>;
  if (isError || !instrument) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this instrument.</div>;

  function submitCalibration(e: React.FormEvent) {
    e.preventDefault();
    logCalibration.mutate(
      { performed_at: new Date().toISOString(), result, next_due_date: nextDueDate },
      { onSuccess: () => setNextDueDate("") },
    );
  }

  return (
    <div>
      <PageHeader
        back={{ to: "/equipment", label: "equipment" }}
        title={instrument.name}
        meta={
          <span className="badge badge-neutral">
            {INSTRUMENT_STATUS_LABELS[instrument.status]}
          </span>
        }
      />

      <div className="detail-grid">
        <div className="stack">
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Details</h2>
            <dl className="field-grid">
              <Field label="Model" value={INSTRUMENT_MODEL_LABELS[instrument.model]} />
              <Field label="Calibration due" value={instrument.calibration_due_date || "—"} />
              <Field label="Custodian" value={instrument.custodian_display_name || "—"} />
            </dl>

            {instrument.child_instruments.length > 0 && (
              <>
                <h2 style={{ fontSize: "1rem", margin: "20px 0 8px" }}>Attached components</h2>
                <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.9rem" }}>
                  {instrument.child_instruments.map((c) => (
                    <li key={c.id} style={{ padding: "6px 0", borderTop: "1px solid var(--color-border)" }}>
                      {c.name} — {INSTRUMENT_MODEL_LABELS[c.model]}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Calibration history</h2>
            {!records || records.results.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No calibration records yet.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Result</th>
                    <th>Performed by</th>
                    <th>Performed</th>
                    <th>Next due</th>
                  </tr>
                </thead>
                <tbody>
                  {records.results.map((r) => (
                    <tr key={r.id} style={{ cursor: "default" }}>
                      <td style={{ textTransform: "capitalize" }}>{r.result}</td>
                      <td>{r.performed_by_display_name || "—"}</td>
                      <td>{new Date(r.performed_at).toLocaleString()}</td>
                      <td>{r.next_due_date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {canWrite && (
          <div className="card" style={{ padding: 20, alignSelf: "start" }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Log calibration</h2>
            <form onSubmit={submitCalibration} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <label style={labelStyle}>
                Result
                <select value={result} onChange={(e) => setResult(e.target.value)}>
                  <option value="pass">Pass</option>
                  <option value="fail">Fail</option>
                  <option value="conditional">Conditional</option>
                </select>
              </label>
              <label style={labelStyle}>
                Next due date
                <input type="date" value={nextDueDate} onChange={(e) => setNextDueDate(e.target.value)} required />
              </label>
              <button type="submit" className="btn btn-primary" disabled={logCalibration.isPending} style={{ alignSelf: "start" }}>
                Log calibration
              </button>
              {logCalibration.isError && (
                <p style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>{describeApiError(logCalibration.error)}</p>
              )}
            </form>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>{label}</dt>
      <dd style={{ margin: "0 0 10px" }}>{value}</dd>
    </>
  );
}

const labelStyle = { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" } as const;
