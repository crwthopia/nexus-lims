import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuotations } from "../api/queries";
import { PageHeader } from "../components/PageHeader";
import { QUOTATION_STATUS_LABELS, SERVICE_LINE_LABELS } from "../api/types";
import type { QuotationStatus } from "../api/types";
import { formatMoney } from "../money";

const STATUS_OPTIONS = Object.keys(QUOTATION_STATUS_LABELS) as QuotationStatus[];

/**
 * Offers the lab has out, and how they were answered.
 *
 * The default view is the two states somebody can still act on — a draft
 * to finish and send, a sent one waiting on the customer. Everything else
 * is history, and a list that opened on it would bury the work.
 */
export function QuotationsList() {
  const [status, setStatus] = useState("draft,sent");
  const { data, isLoading, isError } = useQuotations({ status: status || undefined });
  const navigate = useNavigate();

  return (
    <div>
      <PageHeader
        title="Quotations"
        description="Priced offers, before any work starts. Accepting one puts the quoted lines on an order at the quoted price."
        actions={
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="btn"
            aria-label="Filter by status"
          >
            <option value="draft,sent">Open</option>
            <option value="">All</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {QUOTATION_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        }
      />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading quotations…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load quotations.</div>}
        {data && data.results.length === 0 && <div className="card-state">Nothing matches this filter.</div>}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Reference</th>
                <th>Customer</th>
                <th>Service line</th>
                <th>Lines</th>
                <th>Total</th>
                <th>Valid until</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((quotation) => (
                <tr key={quotation.id} onClick={() => navigate(`/quotations/${quotation.id}`)}>
                  <td style={{ fontWeight: 600 }}>{quotation.reference}</td>
                  <td>{quotation.customer_email}</td>
                  <td>{SERVICE_LINE_LABELS[quotation.service_line]}</td>
                  <td>{quotation.item_count}</td>
                  <td>
                    {quotation.totals.currency
                      ? formatMoney(quotation.totals.gross, quotation.totals.currency)
                      : "—"}
                  </td>
                  <td>{quotation.valid_until}</td>
                  <td>
                    <span className="badge badge-neutral">{QUOTATION_STATUS_LABELS[quotation.status]}</span>
                    {/* The sweep runs nightly, so a quotation can be past
                        its date while still stored as sent. Saying "Sent"
                        alone there would be a lie by one day. */}
                    {quotation.status === "sent" && quotation.is_expired && (
                      <span className="badge badge-neutral" style={{ marginLeft: 6 }}>
                        lapsed
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && (
        <div style={{ marginTop: 12, color: "var(--color-text-muted)", fontSize: "0.85rem" }}>{data.count} total</div>
      )}
    </div>
  );
}
