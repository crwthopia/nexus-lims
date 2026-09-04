/**
 * One description of the console's navigation, read by both the rail
 * (Layout.tsx) and the command palette (CommandPalette.tsx).
 *
 * Kept as data rather than JSX for a reason that showed up the first time
 * the two disagreed: a destination reachable from the rail but not from
 * Ctrl-K, or worse, one the palette offered to a user whose role can't open
 * it. Role gating lives here so it is applied once, on the way out.
 *
 * The sections mirror how a lab actually divides the work, not the URL
 * space: Worklist is what an analyst lives in all day, Quality is what a QA
 * officer opens, Commercial is billing. The rail's grouping is the only
 * thing that kept it readable once it passed a dozen entries.
 */

import type { RoleName } from "../api/types";
import type { IconName } from "./Icon";

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** Undefined means every signed-in user sees it. */
  roles?: RoleName[];
  /** Extra words the palette matches on, for entries whose label isn't what
      a user would type -- "COA" for Reports, "CAPA" for Investigations. */
  keywords?: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

const SECTIONS: NavSection[] = [
  {
    label: "Workspace",
    items: [
      { to: "/dashboard", label: "Dashboard", icon: "dashboard", keywords: "overview analytics leading analyses revenue turnaround" },
    ],
  },
  {
    label: "Worklist",
    items: [
      { to: "/samples", label: "Samples", icon: "samples", keywords: "specimens chain of custody" },
      {
        to: "/testing-queue",
        label: "Testing Queue",
        icon: "testing",
        roles: ["analyst", "reviewer", "qa_officer", "lab_supervisor"],
        keywords: "results entry",
      },
      {
        to: "/review-queue",
        label: "Review Queue",
        icon: "review",
        roles: ["reviewer", "approver", "qa_officer", "lab_supervisor"],
        keywords: "approve sign off",
      },
      { to: "/reports", label: "Reports", icon: "reports", keywords: "coa certificate of analysis pdf" },
    ],
  },
  {
    label: "Quality",
    items: [
      { to: "/documents", label: "Documents", icon: "documents", keywords: "sop controlled" },
      { to: "/investigations", label: "Investigations", icon: "investigations", keywords: "capa nonconformity oos" },
      { to: "/system-failures", label: "System failures", icon: "system", keywords: "iso 17025 incidents" },
    ],
  },
  {
    label: "Laboratory",
    items: [
      { to: "/equipment", label: "Equipment", icon: "equipment", keywords: "instruments calibration" },
      { to: "/training", label: "Training", icon: "training", keywords: "courses competency enrolment" },
    ],
  },
  {
    label: "Commercial",
    items: [
      { to: "/catalogue", label: "Catalogue", icon: "catalogue", keywords: "services price list rate card offerings analyses" },
      { to: "/billing", label: "Billing", icon: "billing", keywords: "invoices payments credit notes" },
    ],
  },
];

/** The sections a holder of `hasRole` may see, with empty ones dropped. */
export function navSections(hasRole: (...roleNames: string[]) => boolean): NavSection[] {
  return SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.roles || hasRole(...item.roles)),
  })).filter((section) => section.items.length > 0);
}

/** The same set, flattened -- what the palette searches. */
export function navItems(hasRole: (...roleNames: string[]) => boolean): NavItem[] {
  return navSections(hasRole).flatMap((section) => section.items);
}

/**
 * The header's title for a path. Detail routes (`/samples/8`) fall back to
 * the section they belong to, so the header always names where you are
 * rather than going blank one level down; the page's own <h1> carries the
 * record's identity.
 */
export function titleForPath(pathname: string): string {
  const match = SECTIONS.flatMap((s) => s.items)
    .filter((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0];
  if (match) return match.label;

  // Detail routes whose collection isn't itself in the rail.
  if (pathname.startsWith("/test-requests/")) return "Testing Queue";
  if (pathname.startsWith("/training-sessions/")) return "Training";
  if (pathname.startsWith("/invoices/")) return "Billing";
  if (pathname.startsWith("/orders/")) return "Samples";
  return "Staff Console";
}
