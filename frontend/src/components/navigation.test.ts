/**
 * The navigation model.
 *
 * `titleForPath` is the header's only source of truth for "where am I", and
 * the case it exists for is the detail routes: `/samples/8` and
 * `/test-requests/3` are not in the rail, and a header that went blank one
 * level below a list would be worse than no header. The other half is role
 * gating, which is applied here so the rail and the palette can't disagree
 * about what a user is allowed to reach.
 */

import { describe, expect, it } from "vitest";
import { navItems, navSections, titleForPath } from "./navigation";

const all = () => true;
const none = () => false;

describe("navSections", () => {
  it("drops the items a user's roles cannot open", () => {
    const labels = navItems(none).map((i) => i.label);

    expect(labels).toContain("Samples");
    expect(labels).not.toContain("Review Queue");
    expect(labels).not.toContain("Testing Queue");
  });

  it("keeps every section non-empty", () => {
    for (const section of navSections(none)) {
      expect(section.items.length).toBeGreaterThan(0);
    }
  });

  it("gives every destination an icon and a unique path", () => {
    const items = navItems(all);
    const paths = items.map((i) => i.to);

    expect(new Set(paths).size).toBe(paths.length);
    expect(items.every((i) => i.icon)).toBe(true);
  });
});

describe("titleForPath", () => {
  it("names the list route", () => {
    expect(titleForPath("/samples")).toBe("Samples");
    expect(titleForPath("/system-failures")).toBe("System failures");
  });

  it("names the section a detail route belongs to", () => {
    expect(titleForPath("/samples/8")).toBe("Samples");
    expect(titleForPath("/equipment/instruments/2")).toBe("Equipment");
  });

  it("names the section for detail routes whose collection is not in the rail", () => {
    expect(titleForPath("/test-requests/3")).toBe("Testing Queue");
    expect(titleForPath("/training-sessions/4")).toBe("Training");
    expect(titleForPath("/invoices/9")).toBe("Billing");
  });

  it("falls back rather than going blank on an unknown path", () => {
    expect(titleForPath("/nowhere")).toBe("Staff Console");
  });
});
