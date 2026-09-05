import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useAddQuotationItem,
  useQuotation,
  useQuotationAction,
  useReviseQuotation,
  useServiceOfferings,
} from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { QUOTATION_STATUS_LABELS, QUOTATION_WRITE_ROLES, SERVICE_LINE_LABELS } from "../api/types";
import { formatMoney } from "../money";

/**
 * One quotation: build it, send it, and record how it was answered.
 *
 * The screen's shape follows the one rule the model enforces — **a sent
 * quotation is immutable**. In draft it is a form; once sent it is a
 * document, the form disappears, and the only way to change the offer is
 * to revise it into a new draft that supersedes this one. Making that
 * visible is the point: a screen that kept the form and quietly failed on
 * save would teach the operator the rule the hard way.
 */
export function QuotationDetail() {
  const { id } = useParams<{ id: string }>();
  const quotationId = Number(id);
  const { data: quotation, isLoading, isError } = useQuotation(quotationId);
  const { hasRole } = useAuth();
  const canWrite = hasRole(...QUOTATION_WRITE_ROLES);
  const navigate = useNavigate();

  const { data: catalogue } = useServiceOfferings({ active: "true" });
  const addItem = useAddQuotationItem(quotationId);
  const send = useQuotationAction(quotationId, "send");
  const accept = useQuotationAction(quotationId, "accept");
  const decline = useQuotationAction(quotationId, "decline");
  const revise = useReviseQuotation(quotationId);

  const [offering, setOffering] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [discount, setDiscount] = useState("0");

  if (isLoading) return <div className="card-state">Loading…</div>;
  if (isError || !quotation) return <div className="card-state card-state-error">Couldn't load this quotation.</div>;

  const isDraft = quotation.status === "draft";
  const isSent = quotation.status === "sent";
  const currency = quotation.totals.currency ?? "PHP";
  const failure = [addItem, send, accept, decline, revise].find((m) => m.isError);

  function submitItem(e: React.FormEvent) {
    e.preventDefault();
    addItem.mutate(
      { offering: Number(offering), quantity: Number(quantity), discount_pct: discount },
      { onSuccess: () => setOffering("") },
    );
  }

  return (
    <div>
      <PageHeader
        back={{ to: "/quotations", label: "quotations" }}
        title={quotation.reference}
        meta={
          <>
            <span className="badge badge-neutral">{QUOTATION_STATUS_LABELS[quotation.status]}</span>
            {isSent && quotation.is_expired && <span className="badge badge-neutral">lapsed</span>}
          </>
        }
        description={`${quotation.customer_email} · ${SERVICE_LINE_LABELS[quotation.service_line]} · valid until ${
          quotation.valid_until
        }`}
      />

      {failure && (
        <div className="card card-state card-state-error" style={{ marginBottom: 20 }}>
          {describeApiError(failure.error)}
        </div>
      )}

      {canWrite && isDraft && (
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
        </form>
      )}

      <div className="detail-grid">
        <div className="stack">
          <div className="card table-card">
            <div className="card-head">
              <div>
                <h2>What is being quoted</h2>
                <p>
                  {isDraft
                    ? "Priced at the rate in force today. Sending fixes these figures."
                    : "The figures the customer was sent. Accepting bills these, whatever the rate card says now."}
                </p>
              </div>
            </div>
            {quotation.items.length === 0 ? (
              <div className="card-state">Nothing quoted yet.</div>
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
                  </tr>
                </thead>
                <tbody>
                  {quotation.items.map((item) => (
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
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {quotation.items.length > 0 && (
            <div style={{ textAlign: "right", fontSize: "0.9rem" }}>
              <span style={{ color: "var(--color-text-muted)" }}>
                Net {formatMoney(quotation.totals.net, currency)} · VAT {formatMoney(quotation.totals.vat, currency)} ·{" "}
              </span>
              <strong>Total {formatMoney(quotation.totals.gross, currency)}</strong>
            </div>
          )}
        </div>

        <div className="stack">
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>
              {isDraft ? "Issue this quotation" : "Where it stands"}
            </h2>

            {!canWrite ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem", margin: 0 }}>
                Requires role: {QUOTATION_WRITE_ROLES.join(" or ")}.
              </p>
            ) : isDraft ? (
              <>
                <button
                  type="button"
                  className="btn btn-primary"
                  style={{ width: "100%" }}
                  disabled={quotation.items.length === 0 || send.isPending}
                  title={quotation.items.length === 0 ? "Add at least one line first." : undefined}
                  onClick={() => send.mutate()}
                >
                  Send to {quotation.customer_email}
                </button>
                <p style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", margin: "10px 0 0" }}>
                  Emails the customer a notice — the figures stay in their account. Once sent, the quotation can't be
                  edited; changing the offer means revising it into a new one.
                </p>
              </>
            ) : isSent ? (
              <>
                {/* Both answers are here because both happen: a customer
                    accepts in the portal, or a purchase order arrives by
                    email and somebody records it. The record tells them
                    apart. */}
                <button
                  type="button"
                  className="btn btn-primary"
                  style={{ width: "100%", marginBottom: 8 }}
                  disabled={quotation.is_expired || accept.isPending}
                  title={quotation.is_expired ? "This quotation has lapsed — revise it instead." : undefined}
                  onClick={() => accept.mutate()}
                >
                  Record acceptance
                </button>
                <button
                  type="button"
                  className="btn"
                  style={{ width: "100%" }}
                  disabled={decline.isPending}
                  onClick={() => decline.mutate()}
                >
                  Record decline
                </button>
                <p style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", margin: "10px 0 0" }}>
                  For an answer that arrived another way — a signed copy, a purchase order. The customer can accept it
                  themselves in the portal.
                </p>
              </>
            ) : (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem", margin: 0 }}>
                {quotation.status === "accepted" && quotation.order ? (
                  <>
                    Accepted, and its lines are on{" "}
                    <a href={`/orders/${quotation.order}`} onClick={(e) => { e.preventDefault(); navigate(`/orders/${quotation.order}`); }}>
                      order #{quotation.order}
                    </a>
                    .
                  </>
                ) : quotation.status === "declined" ? (
                  "The customer declined this offer."
                ) : (
                  "This offer lapsed without an answer."
                )}
              </p>
            )}

            {canWrite && !isDraft && (
              <button
                type="button"
                className="btn"
                style={{ width: "100%", marginTop: 12 }}
                disabled={revise.isPending}
                onClick={() =>
                  revise.mutate(undefined, { onSuccess: (draft) => navigate(`/quotations/${draft.id}`) })
                }
              >
                Revise into a new quotation
              </button>
            )}
          </div>

          {quotation.notes && (
            <div className="card" style={{ padding: 20 }}>
              <h2 style={{ fontSize: "1rem", margin: "0 0 8px" }}>Notes</h2>
              <p style={{ margin: 0, fontSize: "0.9rem", whiteSpace: "pre-wrap" }}>{quotation.notes}</p>
            </div>
          )}

          {quotation.supersedes && (
            <div className="card" style={{ padding: 20 }}>
              <h2 style={{ fontSize: "1rem", margin: "0 0 8px" }}>Supersedes</h2>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => navigate(`/quotations/${quotation.supersedes}`)}
              >
                Quotation #{quotation.supersedes}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
