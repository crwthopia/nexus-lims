/**
 * The catalogue list.
 *
 * The rule this screen has to keep is that a reader can compare two rows.
 * NASAT quotes some rates VAT-exclusive and some VAT-inclusive, so the
 * published `amount` of one offering is not comparable with the next one's;
 * the table shows the server's net and gross for both, and says which way
 * each was quoted. A regression here is silent -- the numbers still render,
 * they are just answering different questions.
 */

import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CatalogueList } from "./CatalogueList";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function price(overrides = {}) {
  return {
    id: 1,
    offering: 1,
    amount: "1000.00",
    currency: "PHP",
    vat_treatment: "exclusive",
    vat_rate_pct: "12.00",
    effective_from: "2026-01-01",
    effective_to: null,
    note: "",
    net_amount: "1000.00",
    vat_amount: "120.00",
    gross_amount: "1120.00",
    is_current: true,
    created_at: "2026-01-01T00:00:00Z",
    created_by: null,
    created_by_display_name: null,
    ...overrides,
  };
}

function offering(overrides = {}) {
  return {
    id: 1,
    code: "WQ-BOD5",
    name: "BOD (5-day)",
    description: "",
    service_line: "water_environmental",
    test_methods: [],
    test_method_names: [],
    turnaround_days: 5,
    is_accredited: false,
    is_active: true,
    current_price: price(),
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function stubCatalogue(results: unknown[], user = staffUser()) {
  stubApi({
    "/auth/staff/me": { body: user },
    "/service-offerings/": { body: { count: results.length, next: null, previous: null, results } },
  });
  return renderWithProviders(<CatalogueList />, { route: "/catalogue", path: "/catalogue" });
}

describe("CatalogueList", () => {
  it("shows net and gross for a VAT-exclusive rate", async () => {
    stubCatalogue([offering()]);

    const row = (await screen.findByText("WQ-BOD5")).closest("tr")!;
    expect(within(row).getByText("₱1,000.00")).toBeInTheDocument();
    expect(within(row).getByText("₱1,120.00")).toBeInTheDocument();
    expect(within(row).getByText("excl.")).toBeInTheDocument();
  });

  it("shows the same two figures for a rate quoted the other way", async () => {
    // 1,120 inclusive is the same money as 1,000 exclusive -- the point of
    // showing the server's derived figures rather than the raw amount.
    stubCatalogue([
      offering({
        code: "FA-SEM",
        current_price: price({ amount: "1120.00", vat_treatment: "inclusive" }),
      }),
    ]);

    const row = (await screen.findByText("FA-SEM")).closest("tr")!;
    expect(within(row).getByText("₱1,000.00")).toBeInTheDocument();
    expect(within(row).getByText("₱1,120.00")).toBeInTheDocument();
    expect(within(row).getByText("incl.")).toBeInTheDocument();
  });

  it("says an offering is unpriced rather than showing a zero", async () => {
    stubCatalogue([offering({ current_price: null })]);

    const row = (await screen.findByText("WQ-BOD5")).closest("tr")!;
    expect(within(row).getByText("not priced")).toBeInTheDocument();
    expect(within(row).queryByText("₱0.00")).not.toBeInTheDocument();
  });

  it("marks a withdrawn offering rather than hiding it", async () => {
    stubCatalogue([offering({ is_active: false })]);

    expect(await screen.findByText("Withdrawn")).toBeInTheDocument();
  });

  it("offers the add form only to a catalogue role", async () => {
    stubCatalogue([offering()], staffUser({ roles: [role("analyst")] }));

    await screen.findByText("WQ-BOD5");
    expect(screen.queryByRole("button", { name: "Add offering" })).not.toBeInTheDocument();
  });

  it("lets a lab supervisor add one", async () => {
    stubCatalogue([offering()], staffUser({ roles: [role("lab_supervisor")] }));

    expect(await screen.findByRole("button", { name: "Add offering" })).toBeInTheDocument();
  });

  it("does not offer Training, which is priced by its own catalogue", async () => {
    stubCatalogue([offering()], staffUser({ roles: [role("lab_supervisor")] }));

    const select = await screen.findByLabelText("Service line");
    expect(within(select).queryByRole("option", { name: /training/i })).not.toBeInTheDocument();
  });

  it("sends the service-line filter to the API", async () => {
    const { calls } = stubApi({
      "/auth/staff/me": { body: staffUser() },
      "/service-offerings/": { body: { count: 0, next: null, previous: null, results: [] } },
    });
    renderWithProviders(<CatalogueList />, { route: "/catalogue", path: "/catalogue" });
    await screen.findByText(/nothing in the catalogue matches/i);

    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.selectOptions(screen.getByLabelText("Filter by service line"), "failure_analysis");

    expect(calls.some((c) => c.url.includes("service_line=failure_analysis"))).toBe(true);
  });
});
