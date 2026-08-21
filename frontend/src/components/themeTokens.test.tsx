/**
 * Both themes must define every token the components reference. A token
 * that exists in one block and not the other does not throw -- the
 * property is simply unset, and the browser falls back to the inherited
 * colour, which in practice means invisible or unreadable text in exactly
 * one theme. That is the failure mode this file exists to catch.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Read off disk rather than imported: Vitest replaces every CSS
// import with an empty string, ?raw included, so an import here
// would assert against "" and pass no matter what the file said.
const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

function tokensIn(selector: string): Set<string> {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`no ${selector} block in index.css`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("\n}", open);
  return new Set(css.slice(open, close).match(/--color-[a-z-]+(?=\s*:)/g) ?? []);
}

describe("theme tokens", () => {
  it("defines the same colour tokens in dark and light", () => {
    const dark = tokensIn(":root {");
    const light = tokensIn(':root[data-theme="light"]');

    expect(dark.size).toBeGreaterThan(15);
    expect([...dark].filter((t) => !light.has(t))).toEqual([]);
    expect([...light].filter((t) => !dark.has(t))).toEqual([]);
  });

  it("defines the brand cyan in both, at different values", () => {
    // Same token, deliberately different value: see the note in index.css.
    expect(css).toContain("--color-brand: #06B6D4");
    expect(css).toContain("--color-brand: #0E7490");
  });
});
