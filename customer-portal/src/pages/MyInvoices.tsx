import { useMyInvoices } from "../api/queries";
import { INVOICE_STATUS_LABELS } from "../api/types";

export function MyInvoices() {
  const { data, isLoading, isError } = useMyInvoices();

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>My Invoices</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>Billing for orders and training.</p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load your invoices.</div>}
        {data && data.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No invoices yet.</div>
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
