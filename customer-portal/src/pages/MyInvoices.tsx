import { useMyInvoices } from "../api/queries";
import { INVOICE_STATUS_LABELS } from "../api/types";
import { PageHeader } from "../components/PageHeader";

export function MyInvoices() {
  const { data, isLoading, isError } = useMyInvoices();

  return (
    <div>
      <PageHeader title="My Invoices" description="Billing for orders and training." />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load your invoices.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">No invoices yet.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((inv) => (
                <tr key={inv.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>#{inv.id}</td>
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
