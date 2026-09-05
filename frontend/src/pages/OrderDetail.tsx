import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAddOrderItem, useInvoiceOrder, useOrder, useServiceOfferings } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { BILLING_WRITE_ROLES, ORDER_ITEM_WRITE_ROLES, SERVICE_LINE_LABELS } from "../api/types";
import { formatMoney } from "../money";

/**
 * What a customer ordered, and what it comes to.
 *
 * The form adds an offering from the catalogue; it never asks for a price,
 * because the server takes one from the rate card in force and a field
 * here would be a way to sell at any figure someone typed. What the screen
 * *does* show is the snapshot that resulted — the unit rate, how it was
 * quoted, and the line's net/VAT/gross — so the person adding a line can
 * see what they just sold.
 *
 * Raising an invoice bills every line not yet billed, which is why the
 * button says so: an order part-billed in March and finished in July gets
 * a second invoice for the July work, not a duplicate of March's.
 */
export function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const orderId = Number(id);
  const { data: order, isLoading, isError } = useOrder(orderId);
  const { hasRole } = useAuth();
  const navigate = useNavigate();

  const canOrder = hasRole(...ORDER_ITEM_WRITE_ROLES);
  const canBill = hasRole(...BILLING_WRITE_ROLES);

  const { data: catalogue } = useServiceOfferings({ active: "true" });
  const addItem = useAddOrderItem(orderId);
  const raiseInvoice = useInvoiceOrder(orderId);

  const [offering, setOffering] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [discount, setDiscount] = useState("0");

  if (isLoading) return <div className="card-state">Loading…</div>;
  if (isError || !order) return <div className="card-state card-state-error">Couldn't load this order.</div>;

  function submitItem(e: React.FormEvent) {
    e.preventDefault();
    addItem.mutate(
      { offering: Number(offering), quantity: Number(quantity), discount_pct: discount },
      { onSuccess: () => setOffering("") },
    );
  }

  const items = order.items;
  const unbilled = items.filter((item) => !item.is_invoiced);
  const totals = items.reduce(
    (sum, item) => ({
      net: sum.net + Number(item.net_amount),
      vat: sum.vat + Number(item.vat_amount),
      gross: sum.gross + Number(item.gross_amount),
    }),
    { net: 0, vat: 0, gross: 0 },
  );

  return (
    <div>
      <PageHeader
        back={{ to: "/samples", label: "samples" }}
        title={`Order #${order.id}`}
        meta={<span className="badge badge-neutral">{SERVICE_LINE_LABELS[order.service_line]}</span>}
        actions={
          canBill && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={unbilled.length === 0 || raiseInvoice.isPending}
              // Says what it will do rather than "Invoice": billing the
              // unbilled remainder is the behaviour, and a button that
              // hides that invites someone to click it twice.
              title={unbilled.length === 0 ? "Every line on this order has been invoiced." : undefined}
              onClick={() =>
                raiseInvoice.mutate(undefined, { onSuccess: (invoice) => navigate(`/invoices/${invoice.id}`) })
              }
            >
              {unbilled.length === 0 ? "Fully invoiced" : `Invoice ${unbilled.length} line${unbilled.length === 1 ? "" : "s"}`}
            </button>
          )
        }
      />

      {raiseInvoice.isError && (
        <div className="card card-state card-state-error" style={{ marginBottom: 20 }}>
          {describeApiError(raiseInvoice.error)}
        </div>
      )}

      {canOrder && (
        <form
          onSubmit={submitItem}
          className="card"
          style={{ padding: 16, marginBottom: 20, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <label className="field" style={{ flex: 1, minWidth: 240 }}>
            Offering
            <select value={offering} onChange={(e) => setOffering(e.target.value)} required>
              <option value="">Choose from the catalogue…</option>
              {catalogue?.results.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.code} — {entry.name}
                  {entry.current_price ? ` (${formatMoney(entry.current_price.net_amount)} net)` : " (unpriced)"}
                </option>
              ))}
            </select>
          </label>
          <label className="field" style={{ width: 90 }}>
            Quantity
            <input value={quantity} onChange={(e) => setQuantity(e.target.value)} inputMode="numeric" />
          </label>
          <label className="field" style={{ width: 110 }}>
            Discount %
            <input value={discount} onChange={(e) => setDiscount(e.target.value)} inputMode="decimal" />
          </label>
          <button type="submit" className="btn btn-primary" disabled={!offering || addItem.isPending}>
            Add line
          </button>
          <p style={{ width: "100%", margin: 0, color: "var(--color-text-muted)", fontSize: "0.8rem" }}>
            The price comes from the rate in force today and is recorded on the line — repricing the catalogue later
            won't change what was sold here.
          </p>
          {addItem.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", margin: 0, width: "100%" }}>
              {describeApiError(addItem.error)}
            </p>
          )}
        </form>
      )}

      <div className="card table-card">
        <div className="card-head">
          <div>
            <h2>Lines</h2>
            <p>Priced when each line was added, not when this page loaded.</p>
          </div>
        </div>
        {items.length === 0 ? (
          <div className="card-state">Nothing ordered yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Offering</th>
                <th>Qty</th>
                <th>Unit</th>
                <th>Disc.</th>
                <th>Net</th>
                <th>VAT</th>
                <th>Gross</th>
                <th>Billed</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} style={{ cursor: "default" }}>
                  <td>
                    <strong>{item.offering_code}</strong> {item.offering_name}
                  </td>
                  <td>{item.quantity}</td>
                  <td>
                    {formatMoney(item.unit_amount, item.currency)}{" "}
                    <span style={{ color: "var(--color-text-muted)" }}>
                      {item.vat_treatment === "inclusive" ? "incl." : "excl."}
                    </span>
                  </td>
                  <td>{Number(item.discount_pct) > 0 ? `${Number(item.discount_pct)}%` : "—"}</td>
                  <td>{formatMoney(item.net_amount, item.currency)}</td>
                  <td>{formatMoney(item.vat_amount, item.currency)}</td>
                  <td>{formatMoney(item.gross_amount, item.currency)}</td>
                  <td>
                    {item.is_invoiced ? (
                      <span className="badge badge-neutral">Invoiced</span>
                    ) : (
                      <span style={{ color: "var(--color-text-muted)" }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {items.length > 0 && (
        <div style={{ marginTop: 12, textAlign: "right", fontSize: "0.9rem" }}>
          <span style={{ color: "var(--color-text-muted)" }}>Net {formatMoney(String(totals.net))} · VAT{" "}
            {formatMoney(String(totals.vat))} · </span>
          <strong>Gross {formatMoney(String(totals.gross))}</strong>
        </div>
      )}
    </div>
  );
}
