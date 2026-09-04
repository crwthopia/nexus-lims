import { useNavigate } from "react-router-dom";
import { useMyQuotations } from "../api/queries";
import { PageHeader } from "../components/PageHeader";
import { QUOTATION_STATUS_LABELS, SERVICE_LINE_LABELS } from "../api/types";
import { formatMoney } from "../money";

/**
 * Quotations the lab has sent this customer.
 *
 * Drafts never reach here — the server excludes them, because a draft is
 * an offer the lab has not made yet, and showing someone a price nobody
 * has decided on is worse than showing them nothing.
 */
export function Quotations() {
  const { data, isLoading, isError } = useMyQuotations();
  const navigate = useNavigate();

  return (
    <div>
      <PageHeader
        title="Quotations"
        description="Priced offers from the lab. Open one to see what it covers and accept or decline it."
      />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load your quotations.</div>}
        {data && data.results.length === 0 && <div className="card-state">No quotations yet.</div>}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Reference</th>
                <th>Service line</th>
                <th>Total</th>
                <th>Valid until</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((quotation) => (
                <tr key={quotation.id} onClick={() => navigate(`/quotations/${quotation.id}`)}>
                  <td style={{ fontWeight: 600 }}>{quotation.reference}</td>
                  <td>{SERVICE_LINE_LABELS[quotation.service_line]}</td>
                  <td>
                    {quotation.totals.currency
                      ? formatMoney(quotation.totals.gross, quotation.totals.currency)
                      : "—"}
                  </td>
                  <td>{quotation.valid_until}</td>
                  <td>
                    {/* "Awaiting your answer" is only true while it can be
                        answered. A lapsed offer says so here rather than
                        inviting a click that will be refused. */}
                    {quotation.status === "sent" && quotation.is_expired
                      ? "Expired"
                      : QUOTATION_STATUS_LABELS[quotation.status]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
