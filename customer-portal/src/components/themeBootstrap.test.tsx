/**
 * The pre-paint script in index.html duplicates two things from
 * src/theme.ts: the storage key, and the default. It has to -- it runs
 * before any module loads, and its whole job is to set data-theme before
 * the first paint so a light-theme user does not see the dark palette
 * flash on every navigation.
 *
 * Duplication that cannot be removed can still be held together. If the
 * key drifts, nothing throws: the inline script reads a key nobody writes,
 * every load starts dark, and the toggle appears to forget the choice on
 * refresh -- a bug that looks like React state and is not.
 */

import { describe, expect, it } from "vitest";
import html from "../../index.html?raw";
import { DEFAULT_THEME, THEME_STORAGE_KEY } from "../theme";

// Vite's ?raw import rather than node:fs: it needs no @types/node, and it
// is resolved by the same bundler that will ship the file, so the test
// reads the index.html this app actually builds from.

describe("the pre-paint theme script", () => {
  it("exists at all", () => {
    // Without it there is no flash-free first paint, and no test below
    // would fail -- they would all pass against an absent script.
    expect(html).toContain("document.documentElement.dataset.theme");
  });

  it("reads the same storage key theme.ts writes", () => {
    expect(html).toContain(`localStorage.getItem("${THEME_STORAGE_KEY}")`);
  });

  it("falls back to the same default theme.ts does", () => {
    // Both the unrecognised-value branch and the throw branch.
    expect(html).toContain(`dataset.theme = "${DEFAULT_THEME}"`);
    expect(html).toContain(`: "${DEFAULT_THEME}"`);
  });

  it("guards the read, since localStorage throws in private browsing", () => {
    expect(html).toMatch(/try\s*\{[\s\S]*localStorage[\s\S]*\}\s*catch/);
  });
});
