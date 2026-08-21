/**
 * Theme selection.
 *
 * Dark is the default and the product's identity (see the note in
 * index.css); light is an explicit choice, remembered per browser.
 *
 * Kept apart from ThemeToggle.tsx because React Fast Refresh's
 * only-export-components rule fires on a module that exports both a
 * component and plain functions -- the same split AuthContext needed.
 */

export type Theme = "dark" | "light";

/** Also read by the inline script in index.html. Changing it means changing both. */
export const THEME_STORAGE_KEY = "nasat-theme";

export const DEFAULT_THEME: Theme = "dark";

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : DEFAULT_THEME;
  } catch {
    // Private browsing and "block site data" both throw on access rather
    // than returning null, so a theme preference must never be load-bearing.
    return DEFAULT_THEME;
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The theme still applies for this page; it just will not be remembered.
  }
}
