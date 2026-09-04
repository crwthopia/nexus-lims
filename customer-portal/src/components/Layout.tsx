import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/context";
import { ThemeToggle } from "./ThemeToggle";
import { Logo } from "./Logo";
import { Icon } from "./Icon";

/**
 * One Layout for every page, public and private alike -- Training is
 * browsable without an account (Blueprint Section 4.3), so there's no
 * clean "public shell" vs. "private shell" split; the nav just adapts to
 * whether `user` is set.
 *
 * A header rather than the Staff Console's nav rail, on purpose: the console
 * is somewhere staff spend a shift, with a dozen grouped destinations worth a
 * permanent 248px; this is six links a customer visits to collect a report,
 * on a page a signed-out visitor can land on cold. Everything under the
 * header -- cards, tables, buttons, badges, forms -- is the console's own CSS,
 * so the two still read as one product.
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
      <header className="topbar">
        <div className="container topbar-inner">
          <Link to="/" className="brand" aria-label="NexusLIMS home">
            <Logo />
          </Link>
          <nav className="topnav" aria-label="Main">
            {user && (
              <>
                <NavLink to="/" end>
                  Orders
                </NavLink>
                <NavLink to="/samples">Samples</NavLink>
                <NavLink to="/reports">Reports</NavLink>
              </>
            )}
            <NavLink to="/training">Training</NavLink>
            {user && (
              <>
                <NavLink to="/my-enrollments">My Enrollments</NavLink>
                <NavLink to="/my-credit-notes">Credit Notes</NavLink>
                <NavLink to="/my-invoices">Invoices</NavLink>
              </>
            )}
          </nav>
          <div className="topbar-right">
            {/* Outside the auth branches: a visitor reading the public course
                catalogue can choose a theme too, and it persists into the
                session they may go on to create. */}
            <ThemeToggle />
            {!isLoading && user && (
              <>
                <Link to="/account" className="account-chip" title={user.email}>
                  <span className="avatar" aria-hidden="true">
                    {initials(user.email)}
                  </span>
                  <span className="truncate">{user.email}</span>
                </Link>
                <button type="button" className="icon-btn" onClick={handleLogout} aria-label="Log out" title="Log out">
                  <Icon name="logout" />
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
      <main className="container" style={{ paddingTop: 28, paddingBottom: 56 }}>
        <Outlet />
      </main>
    </div>
  );
}

/**
 * Two letters from an email address, for the account chip: "jam.cosico@" ->
 * "JC". A customer has no display name here -- the portal only ever knows the
 * address they signed up with -- so the local part is what there is to work
 * with, and anything past the first two initials would not fit the circle.
 */
function initials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._+-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : `${parts[0][0]}${parts[1][0]}`;
  return letters.toUpperCase();
}
