import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/**
 * One Layout for every page, public and private alike -- Training is
 * browsable without an account (Blueprint Section 4.3), so there's no
 * clean "public shell" vs. "private shell" split; the nav just adapts to
 * whether `user` is set.
 */
export function Layout() {
  const { user, isLoading, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div>
      <header style={{ borderBottom: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
        <div className="container" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 60 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
            <Link to="/" style={{ fontWeight: 700, color: "var(--color-text)", textDecoration: "none" }}>
              NASAT Labs
            </Link>
            <nav style={{ display: "flex", gap: 18 }}>
              {user && (
                <>
                  <NavLink to="/" end style={navStyle}>
                    Orders
                  </NavLink>
                  <NavLink to="/samples" style={navStyle}>
                    Samples
                  </NavLink>
                </>
              )}
              <NavLink to="/training" style={navStyle}>
                Training
              </NavLink>
              {user && (
                <>
                  <NavLink to="/my-enrollments" style={navStyle}>
                    My Enrollments
                  </NavLink>
                  <NavLink to="/my-credit-notes" style={navStyle}>
                    Credit Notes
                  </NavLink>
                  <NavLink to="/my-invoices" style={navStyle}>
                    Invoices
                  </NavLink>
                </>
              )}
            </nav>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {!isLoading && user && (
              <>
                <Link to="/account" style={{ fontSize: "0.85rem", color: "var(--color-text-muted)", textDecoration: "none" }}>
                  {user.email}
                </Link>
                <button className="btn" onClick={handleLogout}>
                  Log out
                </button>
              </>
            )}
            {!isLoading && !user && (
              <>
                <Link to="/login" className="btn">
                  Log in
                </Link>
                <Link to="/register" className="btn btn-primary">
                  Register
                </Link>
              </>
            )}
          </div>
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
    // fill colour and only reaches 4.38:1 as text on this surface. Same fix
    // as the Staff Console's Layout -- see the README's Theme section.
    color: isActive ? "var(--color-accent)" : "var(--color-text-muted)",
    fontWeight: 600,
    fontSize: "0.9rem",
    textDecoration: "none",
  };
}
