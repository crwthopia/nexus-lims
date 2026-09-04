import { useParams } from "react-router-dom";
import { useMyOrder } from "../api/queries";
import { PageHeader } from "../components/PageHeader";
import { INVOICE_STATUS_LABELS, ORDER_STATUS_LABELS, SERVICE_LINE_LABELS } from "../api/types";
import { formatMoney } from "../money";

/**
 * One of the customer's own orders: what was tested, at what rate, and
 * what has been billed so far.
 *
 * The page states the VAT treatment on every line because NASAT quotes
 * both ways, and a column of rates where some include VAT and some do not
 * is a column that invites the wrong comparison. The totals come from the
 * server for the same reason: adding a net line to a gross one is wrong by
 * 12%, on the page a customer is most likely to check against their own
 * records.
 *
 * "Not yet invoiced" is shown rather than hidden. A customer looking at an
 * order wants to know what is still coming.
 */
export function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: order, isLoading, isError } = useMyOrder(Number(id));

  if (isLoading) return <div className="card-state">Loading…</div>;
  if (isError || !order) return <div className="card-state card-state-error">Couldn't load this order.</div>;

  const currency = order.totals.currency ?? "PHP";

  return (
    <div>
      <PageHeader
        back={{ to: "/", label: "orders" }}
        title={`Order #${order.id}`}
        description={`${SERVICE_LINE_LABELS[order.service_line]} · placed ${new Date(
          order.created_at,
        ).toLocaleDateString()}`}
        meta={<span className="badge badge-neutral">{ORDER_STATUS_LABELS[order.status]}</span>}
      />

      <div className="card table-card">
        <div className="card-head">
          <div>
            <h2>What you ordered</h2>
            <p>Priced at the rate in force when each line was placed.</p>
          </div>
        </div>
        {order.items.length === 0 ? (
          <div className="card-state">Nothing has been added to this order yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Test</th>
                <th>Qty</th>
                <th>Unit</th>
                <th>Discount</th>
                <th>Net</th>
                <th>VAT</th>
                <th>Total</th>
                <th>Billing</th>
              </tr>
            </thead>
            <tbody>
              {order.items.map((item) => (
                <tr key={item.id} style={{ cursor: "default" }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{item.offering_name}</div>
                    {/* On its own line: beside the name it broke mid-code
                        as soon as the column narrowed. */}
                    <div style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>{item.offering_code}</div>
                  </td>
                  <td>{item.quantity}</td>
                  <td>
                    {formatMoney(item.unit_amount, item.currency)}{" "}
                    <span style={{ color: "var(--color-text-muted)" }}>
                      {item.vat_treatment === "inclusive" ? "incl. VAT" : "+ VAT"}
                    </span>
                  </td>
                  <td>{Number(item.discount_pct) > 0 ? `${Number(item.discount_pct)}%` : "—"}</td>
                  <td>{formatMoney(item.net_amount, item.currency)}</td>
                  <td>{formatMoney(item.vat_amount, item.currency)}</td>
                  <td>{formatMoney(item.gross_amount, item.currency)}</td>
                  <td style={{ color: "var(--color-text-muted)" }}>
                    {item.is_invoiced ? "Invoiced" : "Not yet invoiced"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {order.items.length > 0 && (
        <div style={{ marginTop: 12, textAlign: "right", fontSize: "0.9rem" }}>
          {order.totals.currency === null ? (
            // Two currencies on one order have no single total; saying so
            // is better than showing a number that is money in neither.
            <span style={{ color: "var(--color-text-muted)" }}>
              This order is priced in more than one currency, so the lines are totalled separately above.
            </span>
          ) : (
            <>
              <span style={{ color: "var(--color-text-muted)" }}>
                Net {formatMoney(order.totals.net, currency)} · VAT {formatMoney(order.totals.vat, currency)} ·{" "}
              </span>
              <strong>Total {formatMoney(order.totals.gross, currency)}</strong>
            </>
          )}
        </div>
      )}

      <div className="card table-card" style={{ marginTop: 24 }}>
        <div className="card-head">
          <div>
            <h2>Invoices for this order</h2>
            <p>Work is invoiced as it is completed, so an order can have more than one.</p>
          </div>
        </div>
        {order.invoices.length === 0 ? (
          <div className="card-state">Nothing has been invoiced yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Issued</th>
                <th>Amount</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {order.invoices.map((invoice) => (
                <tr key={invoice.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>#{invoice.id}</td>
                  <td>{new Date(invoice.created_at).toLocaleDateString()}</td>
                  <td>{formatMoney(invoice.amount, invoice.currency)}</td>
                  <td>{INVOICE_STATUS_LABELS[invoice.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
