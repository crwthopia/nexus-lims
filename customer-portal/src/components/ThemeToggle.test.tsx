/**
 * Theme selection.
 *
 * The load-bearing part is that a stored preference must never break the
 * app: localStorage throws outright in private browsing and under "block
 * site data", rather than returning null, so every read and write is
 * wrapped. A theme is a convenience; failing to read one is not a reason
 * for a lab technician to see a blank screen.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "./ThemeToggle";
import { DEFAULT_THEME, readTheme, THEME_STORAGE_KEY, applyTheme } from "../theme";

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("readTheme", () => {
  it("defaults to dark, which is the product's identity", () => {
    expect(readTheme()).toBe("dark");
    expect(DEFAULT_THEME).toBe("dark");
  });

  it("returns a stored choice", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    expect(readTheme()).toBe("light");
  });

  it("ignores a stored value that is not a theme", () => {
    // Anything can end up in localStorage -- another tab, an older build,
    // a user poking at devtools. An unrecognised value must not become a
    // data-theme attribute that matches no CSS block, which would render
    // the dark palette's text on whatever ground the UA picked.
    localStorage.setItem(THEME_STORAGE_KEY, "solarized");
    expect(readTheme()).toBe("dark");
  });

  it("falls back to the default when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("The operation is insecure.");
    });
    expect(readTheme()).toBe("dark");
  });
});

describe("applyTheme", () => {
  it("sets the attribute the stylesheet keys on", () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("still applies the theme when the write throws", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    applyTheme("light");
    // The page is themed for this visit even though nothing was remembered.
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

describe("ThemeToggle", () => {
  it("is labelled with what happens, not with what is true now", async () => {
    render(<ThemeToggle />);
    // Default is dark, so the button offers light.
    expect(screen.getByRole("button", { name: "Light" })).toBeInTheDocument();
  });

  it("switches the document to light and back", async () => {
    render(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");

    await userEvent.click(screen.getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("remembers the choice", async () => {
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Light" }));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("opens on the stored choice rather than the default", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Dark" })).toBeInTheDocument();
  });
});
