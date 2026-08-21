import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/context";
import { ThemeToggle } from "./ThemeToggle";

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
        {/*
          Full-width bar, unlike <main>, which stays in the 1100px reading
          container. The nav outgrew 1100px once Reports was added, and a
          constrained header would either wrap to two rows or clip a link.
          A full-width top bar over constrained content is also what the
          NexusCRM console this theme matches does.
        */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 20,
            height: 60,
            padding: "0 24px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 20, minWidth: 0 }}>
            <Link to="/" style={{ fontWeight: 700, color: "var(--color-text)", textDecoration: "none", whiteSpace: "nowrap" }}>
              NASAT LIMS
            </Link>
            <nav style={{ display: "flex", gap: 14, overflowX: "auto", minWidth: 0 }}>
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
              <NavLink to="/reports" style={navStyle}>
                Reports
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
              <ThemeToggle />
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
    // --color-accent, not --color-primary: the primary blue is the button
    // *fill* colour and only reaches 4.38:1 as text on the header surface.
    // The accent is the text-on-dark variant (6.75:1). See the README's
    // Theme section.
    color: isActive ? "var(--color-accent)" : "var(--color-text-muted)",
    fontWeight: 600,
    fontSize: "0.9rem",
    textDecoration: "none",
    // The nav is one line; without this, adding a link makes the labels
    // themselves wrap and the header grows to two rows.
    whiteSpace: "nowrap" as const,
  };
}
