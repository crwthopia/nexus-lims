import { useState } from "react";
import { useParams } from "react-router-dom";
import { useInvoice, useRecordPayment } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import {
  BILLING_WRITE_ROLES,
  INVOICE_STATUS_LABELS,
  PAYMENT_METHOD_LABELS,
  PAYMENT_STATUS_LABELS,
} from "../api/types";
import type { PaymentMethod, PaymentStatus } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { formatMoney } from "../money";

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
      <PageHeader
        back={{ to: "/billing", label: "billing" }}
        title={`Invoice #${invoice.id}${invoice.customer_email ? ` — ${invoice.customer_email}` : ""}`}
        meta={<span className="badge badge-neutral">{INVOICE_STATUS_LABELS[invoice.status]}</span>}
      />

      <div className="detail-grid">
        <div className="stack">
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Details</h2>
            <dl className="field-grid">
              {/* Net and VAT come from the lines and are absent on an
                  invoice billed as one typed figure — there is no split to
                  report there, and inventing one would be a claim the
                  record doesn't support. */}
              {invoice.net_total !== null && (
                <Field label="Net" value={formatMoney(invoice.net_total, invoice.currency)} />
              )}
              {invoice.vat_total !== null && (
                <Field label="VAT" value={formatMoney(invoice.vat_total, invoice.currency)} />
              )}
              <Field label={invoice.net_total === null ? "Amount" : "Total"} value={formatMoney(invoice.amount, invoice.currency)} />
              <Field label="Order" value={invoice.order ? `#${invoice.order}` : "—"} />
              <Field label="Enrollment" value={invoice.enrollment ? `#${invoice.enrollment}` : "—"} />
              <Field label="Created" value={new Date(invoice.created_at).toLocaleString()} />
            </dl>
          </div>

          <div className="card table-card">
            <div className="card-head">
              <div>
                <h2>What is being billed</h2>
                <p>
                  Snapshotted when the invoice was raised — renaming an offering or repricing the rate card never
                  rewrites an invoice that was sent.
                </p>
              </div>
            </div>
            {invoice.lines.length === 0 ? (
              <div className="card-state">
                Billed as a single amount, with no line breakdown — a walk-in job or a training enrollment.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Description</th>
                    <th>Qty</th>
                    <th>Unit</th>
                    <th>Net</th>
                    <th>VAT</th>
                    <th>Gross</th>
                  </tr>
                </thead>
                <tbody>
                  {invoice.lines.map((line) => (
                    <tr key={line.id} style={{ cursor: "default" }}>
                      <td>{line.description}</td>
                      <td>{line.quantity}</td>
                      <td>
                        {formatMoney(line.unit_amount, line.currency)}{" "}
                        <span style={{ color: "var(--color-text-muted)" }}>
                          {line.vat_treatment === "inclusive" ? "incl." : "excl."}
                        </span>
                      </td>
                      <td>{formatMoney(line.net_amount, line.currency)}</td>
                      <td>{formatMoney(line.vat_amount, line.currency)}</td>
                      <td>{formatMoney(line.gross_amount, line.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
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
                <select value={method} onChange={(e) => setMethod(e.target.value as PaymentMethod)}>
                  {PAYMENT_METHODS.map((m) => (
                    <option key={m} value={m}>
                      {PAYMENT_METHOD_LABELS[m]}
                    </option>
                  ))}
                </select>
              </label>
              <label style={labelStyle}>
                Reference number
                <input value={referenceNumber} onChange={(e) => setReferenceNumber(e.target.value)} />
              </label>
              <label style={labelStyle}>
                Status
                <select value={status} onChange={(e) => setStatus(e.target.value as PaymentStatus)}>
                  {PAYMENT_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {PAYMENT_STATUS_LABELS[s]}
                    </option>
                  ))}
                </select>
              </label>
              <label style={labelStyle}>
                Notes
                <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
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

const labelStyle = { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" } as const;
