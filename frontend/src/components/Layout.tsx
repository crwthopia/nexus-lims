import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/context";
import { ThemeToggle } from "./ThemeToggle";
import { Logo } from "./Logo";
import { Icon } from "./Icon";
import { CommandPalette } from "./CommandPalette";
import { navSections, titleForPath } from "./navigation";
import { isNarrowViewport, readSidebarCollapsed, writeSidebarCollapsed } from "../sidebar";

/**
 * The console shell: a fixed nav rail, a sticky header, and the routed
 * screen between them -- the same arrangement as the NexusCRM Enterprise
 * console this product's theme is matched to, so someone who works in both
 * doesn't have to relearn where things are.
 *
 * It replaced a single row of top-level links, which had run out of room:
 * ten destinations across one line left no space for a section label, so
 * Documents, Investigations and System failures sat beside Billing with
 * nothing saying they were different kinds of work. The rail groups them
 * (see navigation.ts) and has room to keep growing.
 *
 * Two states are remembered or derived rather than assumed:
 * - collapsed, persisted per browser (sidebar.ts), for people who want the
 *   full width for a wide worklist;
 * - narrow, where the rail leaves the flow and becomes a drawer, because a
 *   248px rail on a phone is most of the screen.
 */
export function Layout() {
  const { user, logout, hasRole } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const [collapsed, setCollapsed] = useState(readSidebarCollapsed);
  const [narrow, setNarrow] = useState(isNarrowViewport);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const sections = navSections(hasRole);

  // Keeps `narrow` honest when the window is resized or a tablet is rotated,
  // so the toggle button doesn't keep collapsing a rail that is currently a
  // drawer.
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(max-width: 900px)");
    const onChange = () => setNarrow(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // A drawer left open over the screen you just navigated to is the classic
  // mobile-nav bug; closing on every path change fixes it for good.
  useEffect(() => setDrawerOpen(false), [pathname]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setPaletteOpen((open) => !open);
      } else if (e.key === "Escape") {
        setDrawerOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const toggleRail = useCallback(() => {
    if (narrow) {
      setDrawerOpen((open) => !open);
      return;
    }
    setCollapsed((was) => {
      writeSidebarCollapsed(!was);
      return !was;
    });
  }, [narrow]);

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
    <div className="app-shell" data-collapsed={collapsed} data-mobile-open={drawerOpen}>
      <nav className="sidebar" aria-label="Sections">
        <Link to="/" className="sidebar-brand" aria-label="NexusLIMS home">
          <Logo compact={collapsed && !narrow} wordmark={!collapsed || narrow} />
          {(!collapsed || narrow) && (
            <span className="brand-text" style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
              Staff
            </span>
          )}
        </Link>

        <div className="sidebar-nav">
          {sections.map((section) => (
            <div className="nav-section" key={section.label}>
              <div className="nav-label" aria-hidden="true">
                {section.label}
              </div>
              {/* The group is labelled for assistive tech too, since the
                  visible label above is hidden from it when collapsed. */}
              <ul aria-label={section.label}>
                {section.items.map((item) => (
                  <li key={item.to}>
                    <NavLink to={item.to} className="nav-item" title={item.label}>
                      <Icon name={item.icon} />
                      <span className="nav-text">{item.label}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {user && (
          <div className="sidebar-foot">
            <div className="user-chip" title={user.display_name}>
              <span className="avatar" aria-hidden="true">
                {initials(user.display_name)}
              </span>
              <span className="user-meta truncate" style={{ minWidth: 0 }}>
                <span className="truncate" style={{ display: "block", fontSize: "0.85rem", fontWeight: 600 }}>
                  {user.display_name}
                </span>
                <span
                  className="truncate"
                  style={{ display: "block", fontSize: "0.75rem", color: "var(--color-text-muted)" }}
                >
                  {roleSummary(user.roles.map((r) => r.name))}
                </span>
              </span>
            </div>
          </div>
        )}
      </nav>

      {/* Only rendered on a narrow viewport, where the rail floats over the
          content: a click anywhere outside it should dismiss it. */}
      {narrow && drawerOpen && (
        <button type="button" className="scrim" aria-label="Close navigation" onClick={() => setDrawerOpen(false)} />
      )}

      <header className="topbar">
        <button
          type="button"
          className="icon-btn"
          onClick={toggleRail}
          aria-label={narrow ? (drawerOpen ? "Close navigation" : "Open navigation") : collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={narrow ? drawerOpen : !collapsed}
        >
          <Icon name="sidebar" />
        </button>
        <h2 className="topbar-title">{titleForPath(pathname)}</h2>

        <div className="topbar-right">
          <button type="button" className="searchbtn" onClick={() => setPaletteOpen(true)}>
            <Icon name="search" size={16} />
            <span>Go to…</span>
            <span className="kbd" aria-hidden="true">
              ⌘K
            </span>
          </button>
          <ThemeToggle />
          {user && (
            <button type="button" className="icon-btn" onClick={handleLogout} aria-label="Log out" title="Log out">
              <Icon name="logout" />
            </button>
          )}
        </div>
      </header>

      <main className="app-main">
        <div className="page">
          <Outlet />
        </div>
      </main>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} hasRole={hasRole} />
    </div>
  );
}

/** "Maria Dela Cruz" -> "MC". Two letters at most: three stop fitting the circle. */
function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : `${parts[0][0]}${parts[parts.length - 1][0]}`;
  return letters.toUpperCase();
}

/**
 * Roles under the name in the rail. The old header printed every role
 * comma-separated, which for a lab supervisor holding five of them wrapped
 * the header onto a second line; here there is one line's worth of space, so
 * beyond two it counts the rest.
 */
function roleSummary(roles: string[]): string {
  if (roles.length === 0) return "No roles assigned";
  const named = roles.slice(0, 2).map((r) => r.replace(/_/g, " "));
  return roles.length > 2 ? `${named.join(", ")} +${roles.length - 2}` : named.join(", ");
}
