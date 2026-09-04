import { useMyOrders } from "../api/queries";
import { ORDER_STATUS_LABELS } from "../api/types";
import { PageHeader } from "../components/PageHeader";

export function Orders() {
  const { data, isLoading, isError } = useMyOrders();

  return (
    <div>
      <PageHeader title="My Orders" description="Lab testing orders placed through NexusLIMS." />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load your orders.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">No orders yet.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Order #</th>
                <th>Service line</th>
                <th>Status</th>
                <th>Placed</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((o) => (
                <tr key={o.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>#{o.id}</td>
                  <td>{o.service_line.replace("_", " ")}</td>
                  <td>{ORDER_STATUS_LABELS[o.status]}</td>
                  <td>{new Date(o.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
