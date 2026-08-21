import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateInstrument, useCreateStandardReagent, useInstruments, useStandardReagents } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { EQUIPMENT_WRITE_ROLES, INSTRUMENT_MODEL_LABELS, INSTRUMENT_STATUS_LABELS } from "../api/types";
import type { InstrumentModel, InstrumentStatus } from "../api/types";

const INSTRUMENT_MODELS = Object.keys(INSTRUMENT_MODEL_LABELS) as InstrumentModel[];
const INSTRUMENT_STATUSES = Object.keys(INSTRUMENT_STATUS_LABELS) as InstrumentStatus[];

export function EquipmentList() {
  const { hasRole } = useAuth();
  const canWrite = hasRole(...EQUIPMENT_WRITE_ROLES);
  const navigate = useNavigate();

  const [statusFilter, setStatusFilter] = useState("");
  const { data: instruments, isLoading: instrumentsLoading } = useInstruments({ status: statusFilter || undefined });
  const { data: reagents, isLoading: reagentsLoading } = useStandardReagents();

  const createInstrument = useCreateInstrument();
  const createReagent = useCreateStandardReagent();

  const [instrumentName, setInstrumentName] = useState("");
  const [instrumentModel, setInstrumentModel] = useState<InstrumentModel>("other");

  const [reagentName, setReagentName] = useState("");
  const [lotNumber, setLotNumber] = useState("");
  const [crmReference, setCrmReference] = useState("");
  const [expiryDate, setExpiryDate] = useState("");

  function submitInstrument(e: React.FormEvent) {
    e.preventDefault();
    createInstrument.mutate(
      { name: instrumentName, model: instrumentModel },
      { onSuccess: (instrument) => navigate(`/equipment/instruments/${instrument.id}`) },
    );
  }

  function submitReagent(e: React.FormEvent) {
    e.preventDefault();
    createReagent.mutate(
      { name: reagentName, lot_number: lotNumber, crm_traceability_reference: crmReference, expiry_date: expiryDate },
      {
        onSuccess: () => {
          setReagentName("");
          setLotNumber("");
          setCrmReference("");
          setExpiryDate("");
        },
      },
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>Equipment</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
          Instruments and standard reagents/reference materials (Blueprint 3.3).
        </p>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "0 0 12px" }}>
        <h2 style={{ fontSize: "1.1rem", margin: 0 }}>Instruments</h2>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="btn" style={{ cursor: "pointer" }}>
          <option value="">All statuses</option>
          {INSTRUMENT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {INSTRUMENT_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      {canWrite && (
        <form
          onSubmit={submitInstrument}
          className="card"
          style={{ padding: 16, marginBottom: 12, display: "flex", gap: 10, alignItems: "flex-end" }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", flex: 1 }}>
            New instrument name
            <input value={instrumentName} onChange={(e) => setInstrumentName(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Model
            <select value={instrumentModel} onChange={(e) => setInstrumentModel(e.target.value as InstrumentModel)} style={inputStyle}>
              {INSTRUMENT_MODELS.map((m) => (
                <option key={m} value={m}>
                  {INSTRUMENT_MODEL_LABELS[m]}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={createInstrument.isPending}>
            Add
          </button>
          {createInstrument.isError && (
            <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{describeApiError(createInstrument.error)}</span>
          )}
        </form>
      )}

      <div className="card" style={{ overflow: "hidden", marginBottom: 32 }}>
        {instrumentsLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {instruments && instruments.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No instruments match this filter.</div>
        )}
        {instruments && instruments.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Model</th>
                <th>Status</th>
                <th>Calibration due</th>
                <th>Custodian</th>
              </tr>
            </thead>
            <tbody>
              {instruments.results.map((i) => (
                <tr key={i.id} onClick={() => navigate(`/equipment/instruments/${i.id}`)}>
                  <td style={{ fontWeight: 600 }}>{i.name}</td>
                  <td>{INSTRUMENT_MODEL_LABELS[i.model]}</td>
                  <td>{INSTRUMENT_STATUS_LABELS[i.status]}</td>
                  <td>{i.calibration_due_date || "—"}</td>
                  <td>{i.custodian_display_name || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2 style={{ fontSize: "1.1rem", margin: "0 0 12px" }}>Standard reagents / reference materials</h2>

      {canWrite && (
        <form
          onSubmit={submitReagent}
          className="card"
          style={{ padding: 16, marginBottom: 12, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", flex: 1, minWidth: 140 }}>
            Name
            <input value={reagentName} onChange={(e) => setReagentName(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Lot number
            <input value={lotNumber} onChange={(e) => setLotNumber(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            CRM traceability reference
            <input value={crmReference} onChange={(e) => setCrmReference(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Expiry date
            <input type="date" value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)} required style={inputStyle} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={createReagent.isPending}>
            Add
          </button>
          {createReagent.isError && (
            <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{describeApiError(createReagent.error)}</span>
          )}
        </form>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        {reagentsLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {reagents && reagents.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No standard reagents yet.</div>
        )}
        {reagents && reagents.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Lot</th>
                <th>CRM reference</th>
                <th>Expiry</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {reagents.results.map((r) => (
                <tr key={r.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>{r.name}</td>
                  <td>{r.lot_number}</td>
                  <td>{r.crm_traceability_reference}</td>
                  <td>{r.expiry_date}</td>
                  <td style={{ textTransform: "capitalize" }}>{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const inputStyle = {
  padding: "6px 8px",
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  fontFamily: "inherit",
  fontSize: "0.9rem",
} as const;
