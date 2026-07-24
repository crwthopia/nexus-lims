import { useState } from "react";
import { useApplyMyCreditNote, useMyCreditNotes } from "../api/queries";
import { describeApiError } from "../api/client";

export function MyCreditNotes() {
  const { data, isLoading, isError } = useMyCreditNotes();
  const applyCreditNote = useApplyMyCreditNote();
  const [targets, setTargets] = useState<Record<number, string>>({});

  function submitApply(creditNoteId: number) {
    const enrollmentId = Number(targets[creditNoteId]);
    if (!enrollmentId) return;
    applyCreditNote.mutate({ creditNoteId, enrollment: enrollmentId });
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>Credit Notes</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
          Redeem a credit against a future training enrollment.
        </p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load your credit notes.</div>}
        {data && data.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No credit notes on your account.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Amount</th>
                <th>Status</th>
                <th>Issued</th>
                <th>Redeem (enrollment #)</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((cn) => (
                <tr key={cn.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>₱{cn.amount}</td>
                  <td style={{ textTransform: "capitalize" }}>{cn.status}</td>
                  <td>{new Date(cn.created_at).toLocaleDateString()}</td>
                  <td>
                    {cn.status === "available" && (
                      <div style={{ display: "flex", gap: 6 }}>
                        <input
                          type="number"
                          placeholder="Enrollment ID"
                          value={targets[cn.id] ?? ""}
                          onChange={(e) => setTargets((prev) => ({ ...prev, [cn.id]: e.target.value }))}
                          style={{ width: 110, padding: "6px 8px", borderRadius: "var(--radius)", border: "1px solid var(--color-border)" }}
                        />
                        <button className="btn" disabled={applyCreditNote.isPending} onClick={() => submitApply(cn.id)}>
                          Apply
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {applyCreditNote.isError && (
          <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", padding: "0 16px 16px" }}>
            {describeApiError(applyCreditNote.error)}
          </p>
        )}
      </div>
    </div>
  );
}
