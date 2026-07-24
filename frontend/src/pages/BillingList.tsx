import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateInvoice, useInvoices } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { describeApiError } from "../api/client";
import { BILLING_WRITE_ROLES, INVOICE_STATUS_LABELS } from "../api/types";
import type { InvoiceStatus } from "../api/types";

const STATUS_OPTIONS = Object.keys(INVOICE_STATUS_LABELS) as InvoiceStatus[];

export function BillingList() {
  const { hasRole } = useAuth();
  const canWrite = hasRole(...BILLING_WRITE_ROLES);
  const navigate = useNavigate();

  const [statusFilter, setStatusFilter] = useState("");
  const { data: invoices, isLoading, isError } = useInvoices({ status: statusFilter || undefined });
  const createInvoice = useCreateInvoice();

  const [target, setTarget] = useState<"order" | "enrollment">("order");
  const [targetId, setTargetId] = useState("");
  const [amount, setAmount] = useState("");

  function submitInvoice(e: React.FormEvent) {
    e.preventDefault();
    const data = target === "order" ? { order: Number(targetId), amount } : { enrollment: Number(targetId), amount };
    createInvoice.mutate(data, {
      onSuccess: (invoice) => navigate(`/invoices/${invoice.id}`),
    });
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>Billing</h1>
          <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>
            Invoices and manual payment reconciliation (Blueprint 3.7).
          </p>
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="btn" style={{ cursor: "pointer" }}>
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {INVOICE_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      {canWrite && (
        <form
          onSubmit={submitInvoice}
          className="card"
          style={{ padding: 16, marginBottom: 12, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Bill against
            <select value={target} onChange={(e) => setTarget(e.target.value as "order" | "enrollment")} style={inputStyle}>
              <option value="order">Order</option>
              <option value="enrollment">Enrollment</option>
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            {target === "order" ? "Order ID" : "Enrollment ID"}
            <input
              type="number"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              required
              style={{ ...inputStyle, width: 120 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Amount (PHP)
            <input value={amount} onChange={(e) => setAmount(e.target.value)} required style={{ ...inputStyle, width: 120 }} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={createInvoice.isPending}>
            Create invoice
          </button>
          {createInvoice.isError && (
            <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{describeApiError(createInvoice.error)}</span>
          )}
        </form>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load invoices.</div>}
        {invoices && invoices.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No invoices match this filter.</div>
        )}
        {invoices && invoices.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {invoices.results.map((inv) => (
                <tr key={inv.id} onClick={() => navigate(`/invoices/${inv.id}`)}>
                  <td style={{ fontWeight: 600 }}>{inv.customer_email || "—"}</td>
                  <td>
                    {inv.currency} {inv.amount}
                  </td>
                  <td>{INVOICE_STATUS_LABELS[inv.status]}</td>
                  <td>{new Date(inv.created_at).toLocaleDateString()}</td>
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
