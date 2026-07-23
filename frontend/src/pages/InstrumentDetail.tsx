import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useCalibrationRecordsForInstrument, useCreateCalibrationRecord, useInstrument } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { describeApiError } from "../api/client";
import { EQUIPMENT_WRITE_ROLES, INSTRUMENT_MODEL_LABELS, INSTRUMENT_STATUS_LABELS } from "../api/types";

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
      <Link to="/equipment" style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
        ← Back to equipment
      </Link>

      <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "12px 0 24px" }}>
        <h1 style={{ fontSize: "1.4rem", margin: 0 }}>{instrument.name}</h1>
        <span className="badge" style={{ background: "var(--color-bg)", color: "var(--color-text-muted)" }}>
          {INSTRUMENT_STATUS_LABELS[instrument.status]}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Details</h2>
            <dl style={fieldGridStyle}>
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
                <select value={result} onChange={(e) => setResult(e.target.value)} style={inputStyle}>
                  <option value="pass">Pass</option>
                  <option value="fail">Fail</option>
                  <option value="conditional">Conditional</option>
                </select>
              </label>
              <label style={labelStyle}>
                Next due date
                <input type="date" value={nextDueDate} onChange={(e) => setNextDueDate(e.target.value)} required style={inputStyle} />
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

const fieldGridStyle = { display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 16, margin: 0 } as const;
const labelStyle = { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" } as const;
const inputStyle = {
  padding: "6px 8px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  fontFamily: "inherit",
  fontSize: "0.9rem",
} as const;
