import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Layout() {
  const { user, logout, hasRole } = useAuth();
  const navigate = useNavigate();
  const canReview = hasRole("reviewer", "approver", "qa_officer", "lab_supervisor");
  const canTest = hasRole("analyst", "reviewer", "qa_officer", "lab_supervisor");

  async function handleLogout() {
    await logout();
    // ProtectedRoute would eventually redirect once the "staff-me" query
    // re-settles as unauthenticated, but that's reactive and can lag a
    // render behind right after queryClient.clear() -- navigating here
    // directly makes the redirect immediate instead of leaving stale
    // authenticated content on screen for a moment.
    navigate("/login", { replace: true });
  }

  return (
    <div>
      <header
        style={{
          borderBottom: "1px solid var(--color-border)",
          background: "var(--color-surface)",
        }}
      >
        <div
          className="container"
          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 60 }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
            <Link to="/" style={{ fontWeight: 700, color: "var(--color-text)", textDecoration: "none" }}>
              NASAT LIMS
            </Link>
            <nav style={{ display: "flex", gap: 18 }}>
              <NavLink to="/samples" style={navStyle}>
                Samples
              </NavLink>
              <NavLink to="/documents" style={navStyle}>
                Documents
              </NavLink>
              <NavLink to="/investigations" style={navStyle}>
                Investigations
              </NavLink>
              <NavLink to="/equipment" style={navStyle}>
                Equipment
              </NavLink>
              <NavLink to="/training" style={navStyle}>
                Training
              </NavLink>
              <NavLink to="/billing" style={navStyle}>
                Billing
              </NavLink>
              {canTest && (
                <NavLink to="/testing-queue" style={navStyle}>
                  Testing Queue
                </NavLink>
              )}
              {canReview && (
                <NavLink to="/review-queue" style={navStyle}>
                  Review Queue
                </NavLink>
              )}
            </nav>
          </div>
          {user && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ textAlign: "right", lineHeight: 1.3 }}>
                <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>{user.display_name}</div>
                <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                  {user.roles.map((r) => r.name).join(", ") || "no roles assigned"}
                </div>
              </div>
              <button className="btn" onClick={handleLogout}>
                Log out
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="container" style={{ paddingTop: 28, paddingBottom: 48 }}>
        <Outlet />
      </main>
    </div>
  );
}

function navStyle({ isActive }: { isActive: boolean }) {
  return {
    color: isActive ? "var(--color-primary)" : "var(--color-text-muted)",
    fontWeight: 600,
    fontSize: "0.9rem",
    textDecoration: "none",
  };
}
