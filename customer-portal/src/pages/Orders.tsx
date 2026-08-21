import { useMyOrders } from "../api/queries";
import { ORDER_STATUS_LABELS } from "../api/types";

export function Orders() {
  const { data, isLoading, isError } = useMyOrders();

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>My Orders</h1>
        <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.9rem" }}>Lab testing orders placed through NexusLIMS.</p>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        {isLoading && <div style={{ padding: 24 }}>Loading…</div>}
        {isError && <div style={{ padding: 24, color: "var(--color-danger)" }}>Couldn't load your orders.</div>}
        {data && data.results.length === 0 && (
          <div style={{ padding: 24, color: "var(--color-text-muted)" }}>No orders yet.</div>
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
