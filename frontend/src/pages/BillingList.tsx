import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateInvoice, useInvoices } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
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
      <PageHeader
        title="Billing"
        description="Invoices and manual payment reconciliation (Blueprint 3.7)."
        actions={
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="btn"
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {INVOICE_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        }
      />

      {canWrite && (
        <form
          onSubmit={submitInvoice}
          className="card"
          style={{ padding: 16, marginBottom: 12, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Bill against
            <select value={target} onChange={(e) => setTarget(e.target.value as "order" | "enrollment")}>
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
              style={{ width: 120 }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Amount (PHP)
            <input value={amount} onChange={(e) => setAmount(e.target.value)} required style={{ width: 120 }} />
          </label>
          <button type="submit" className="btn btn-primary" disabled={createInvoice.isPending}>
            Create invoice
          </button>
          {createInvoice.isError && (
            <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{describeApiError(createInvoice.error)}</span>
          )}
        </form>
      )}

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load invoices.</div>}
        {invoices && invoices.results.length === 0 && (
          <div className="card-state">No invoices match this filter.</div>
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

