import { useNavigate, useParams } from "react-router-dom";
import { useAnswerQuotation, useMyQuotation } from "../api/queries";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { QUOTATION_STATUS_LABELS, SERVICE_LINE_LABELS } from "../api/types";
import { formatMoney } from "../money";

/**
 * One offer, and the customer's answer to it.
 *
 * Accepting is the only place in this portal where a customer commits to
 * money, so the page states the terms next to the button rather than
 * anywhere else: the total, the date the offer lapses, and what happens
 * next. The figures are the ones the lab quoted — accepting bills these,
 * whatever the rate card says by then, which is the promise a quotation
 * makes and the reason it is worth having.
 */
export function QuotationDetail() {
  const { id } = useParams<{ id: string }>();
  const quotationId = Number(id);
  const { data: quotation, isLoading, isError } = useMyQuotation(quotationId);
  const accept = useAnswerQuotation(quotationId, "accept");
  const decline = useAnswerQuotation(quotationId, "decline");
  const navigate = useNavigate();

  if (isLoading) return <div className="card-state">Loading…</div>;
  if (isError || !quotation) return <div className="card-state card-state-error">Couldn't load this quotation.</div>;

  const currency = quotation.totals.currency ?? "PHP";
  // Answerable only while it is open *and* still in date: the lab's
  // nightly sweep can lag a lapse by up to a day, so the date decides.
  const open = quotation.status === "sent" && !quotation.is_expired;
  const failure = [accept, decline].find((m) => m.isError);

  return (
    <div>
      <PageHeader
        back={{ to: "/quotations", label: "quotations" }}
        title={quotation.reference}
        description={`${SERVICE_LINE_LABELS[quotation.service_line]} · valid until ${quotation.valid_until}`}
        meta={
          <span className="badge badge-neutral">
            {quotation.status === "sent" && quotation.is_expired
              ? "Expired"
              : QUOTATION_STATUS_LABELS[quotation.status]}
          </span>
        }
      />

      {failure && (
        <div className="card card-state card-state-error" style={{ marginBottom: 20 }}>
          {describeApiError(failure.error)}
        </div>
      )}

      <div className="card table-card">
        <div className="card-head">
          <div>
            <h2>What is being offered</h2>
            <p>Accepting these lines puts them on an order at exactly these prices.</p>
          </div>
        </div>
        {quotation.items.length === 0 ? (
          <div className="card-state">This quotation has no lines.</div>
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
              </tr>
            </thead>
            <tbody>
              {quotation.items.map((item) => (
                <tr key={item.id} style={{ cursor: "default" }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{item.offering_name}</div>
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
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {quotation.items.length > 0 && (
        <div style={{ marginTop: 12, textAlign: "right", fontSize: "0.9rem" }}>
          <span style={{ color: "var(--color-text-muted)" }}>
            Net {formatMoney(quotation.totals.net, currency)} · VAT {formatMoney(quotation.totals.vat, currency)} ·{" "}
          </span>
          <strong>Total {formatMoney(quotation.totals.gross, currency)}</strong>
        </div>
      )}

      {quotation.notes && (
        <div className="card" style={{ padding: 20, marginTop: 24 }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 8px" }}>Terms and notes</h2>
          <p style={{ margin: 0, fontSize: "0.9rem", whiteSpace: "pre-wrap" }}>{quotation.notes}</p>
        </div>
      )}

      <div className="card" style={{ padding: 20, marginTop: 24 }}>
        {open ? (
          <>
            <h2 style={{ fontSize: "1rem", margin: "0 0 4px" }}>Your answer</h2>
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem", margin: "0 0 16px" }}>
              Accepting places an order for the lines above at{" "}
              <strong>{formatMoney(quotation.totals.gross, currency)}</strong> including VAT, and the lab begins work.
              This offer lapses on {quotation.valid_until}.
            </p>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={accept.isPending || decline.isPending}
                onClick={() => accept.mutate()}
              >
                Accept this quotation
              </button>
              <button
                type="button"
                className="btn"
                disabled={accept.isPending || decline.isPending}
                onClick={() => decline.mutate()}
              >
                Decline
              </button>
            </div>
          </>
        ) : (
          <p style={{ margin: 0, fontSize: "0.9rem" }}>
            {quotation.status === "accepted" ? (
              <>
                You accepted this quotation
                {quotation.decided_at ? ` on ${new Date(quotation.decided_at).toLocaleDateString()}` : ""}.
                {quotation.order && (
                  <>
                    {" "}
                    It became{" "}
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => navigate(`/orders/${quotation.order}`)}
                    >
                      order #{quotation.order}
                    </button>
                    .
                  </>
                )}
              </>
            ) : quotation.status === "declined" ? (
              "You declined this quotation. Ask the lab for a new one if anything has changed."
            ) : (
              `This offer lapsed on ${quotation.valid_until}. Ask the lab to re-issue it if you would still like the work.`
            )}
          </p>
        )}
      </div>
    </div>
  );
}
