import { useState } from "react";
import { useApplyMyCreditNote, useMyCreditNotes } from "../api/queries";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";

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
      <PageHeader title="Credit Notes" description="Redeem a credit against a future training enrollment." />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load your credit notes.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">No credit notes on your account.</div>
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
                          style={{ width: 110 }}
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
