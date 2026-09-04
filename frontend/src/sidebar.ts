/**
 * Whether the nav rail is collapsed to icons, remembered per browser.
 *
 * Same shape and the same care as theme.ts: `localStorage` throws outright
 * in private browsing and under "block site data" rather than returning
 * null, so both the read and the write are wrapped. A rail that forgets its
 * width is a nuisance; one that throws on load is a blank console.
 *
 * Kept out of Layout.tsx because a module exporting both a component and
 * plain functions breaks React Fast Refresh -- the same split theme.ts and
 * auth/context.ts already needed.
 */

export const SIDEBAR_STORAGE_KEY = "nasat-sidebar-collapsed";

export function readSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function writeSidebarCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
  } catch {
    // The rail still moves for this visit; it just will not be remembered.
  }
}

/** The rail is a drawer below this width -- mirrors the media query in index.css. */
export const NARROW_QUERY = "(max-width: 900px)";

export function isNarrowViewport(): boolean {
  // jsdom (and any non-browser render) has no matchMedia; the desktop rail
  // is the safe assumption there.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(NARROW_QUERY).matches;
}
