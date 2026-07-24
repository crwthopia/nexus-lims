import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useInvoice, useRecordPayment } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { describeApiError } from "../api/client";
import {
  BILLING_WRITE_ROLES,
  INVOICE_STATUS_LABELS,
  PAYMENT_METHOD_LABELS,
  PAYMENT_STATUS_LABELS,
} from "../api/types";
import type { PaymentMethod, PaymentStatus } from "../api/types";

const PAYMENT_METHODS = Object.keys(PAYMENT_METHOD_LABELS) as PaymentMethod[];
const PAYMENT_STATUSES = Object.keys(PAYMENT_STATUS_LABELS) as PaymentStatus[];

export function InvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const invoiceId = Number(id);
  const { data: invoice, isLoading, isError } = useInvoice(invoiceId);
  const { hasRole } = useAuth();
  const canWrite = hasRole(...BILLING_WRITE_ROLES);
  const recordPayment = useRecordPayment(invoiceId);

  const [method, setMethod] = useState<PaymentMethod>("bank_transfer");
  const [referenceNumber, setReferenceNumber] = useState("");
  const [status, setStatus] = useState<PaymentStatus>("confirmed");
  const [notes, setNotes] = useState("");

  if (isLoading) return <div>Loading…</div>;
  if (isError || !invoice) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this invoice.</div>;

  function submitPayment(e: React.FormEvent) {
    e.preventDefault();
    recordPayment.mutate(
      { method, reference_number: referenceNumber || undefined, status, notes: notes || undefined },
      { onSuccess: () => setReferenceNumber("") },
    );
  }

  return (
    <div>
      <Link to="/billing" style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
        ← Back to billing
      </Link>

      <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "12px 0 24px" }}>
        <h1 style={{ fontSize: "1.4rem", margin: 0 }}>
          Invoice #{invoice.id}
          {invoice.customer_email && ` — ${invoice.customer_email}`}
        </h1>
        <span className="badge" style={{ background: "var(--color-bg)", color: "var(--color-text-muted)" }}>
          {INVOICE_STATUS_LABELS[invoice.status]}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Details</h2>
            <dl style={fieldGridStyle}>
              <Field label="Amount" value={`${invoice.currency} ${invoice.amount}`} />
              <Field label="Order" value={invoice.order ? `#${invoice.order}` : "—"} />
              <Field label="Enrollment" value={invoice.enrollment ? `#${invoice.enrollment}` : "—"} />
              <Field label="Created" value={new Date(invoice.created_at).toLocaleString()} />
            </dl>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Payments</h2>
            {invoice.payments.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No payments recorded yet.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Method</th>
                    <th>Reference</th>
                    <th>Status</th>
                    <th>Recorded by</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {invoice.payments.map((p) => (
                    <tr key={p.id} style={{ cursor: "default" }}>
                      <td>{PAYMENT_METHOD_LABELS[p.method]}</td>
                      <td>{p.reference_number || "—"}</td>
                      <td>{PAYMENT_STATUS_LABELS[p.status]}</td>
                      <td>{p.recorded_by_display_name}</td>
                      <td>{p.notes || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {canWrite && invoice.status !== "void" && (
          <div className="card" style={{ padding: 20, alignSelf: "start" }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Record a payment</h2>
            <form onSubmit={submitPayment} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <label style={labelStyle}>
                Method
                <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)} style={inputStyle}>
                  {PAYMENT_METHODS.map((m) => (
                    <option key={m} value={m}>
                      {PAYMENT_METHOD_LABELS[m]}
                    </option>
                  ))}
                </select>
              </label>
              <label style={labelStyle}>
                Reference number
                <input value={referenceNumber} onChange={(e) => setReferenceNumber(e.target.value)} style={inputStyle} />
              </label>
              <label style={labelStyle}>
                Status
                <select value={status} onChange={(e) => setStatus(e.target.value as PaymentStatus)} style={inputStyle}>
                  {PAYMENT_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {PAYMENT_STATUS_LABELS[s]}
                    </option>
                  ))}
                </select>
              </label>
              <label style={labelStyle}>
                Notes
                <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} style={inputStyle} />
              </label>
              <button type="submit" className="btn btn-primary" disabled={recordPayment.isPending} style={{ alignSelf: "start" }}>
                Record payment
              </button>
              {recordPayment.isError && (
                <p style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>{describeApiError(recordPayment.error)}</p>
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
