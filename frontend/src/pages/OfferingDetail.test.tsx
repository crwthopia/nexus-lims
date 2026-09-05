/**
 * One catalogue entry and its price history.
 *
 * Two behaviours are load-bearing here. Repricing must post a *new* price
 * rather than patch the current one -- the server closes the outgoing rate
 * so an invoice raised in March keeps quoting March's, and a screen that
 * PATCHed the row would erase exactly that. And the effective date must be
 * omitted when blank rather than sent as "", which is not a date and which
 * the server would reject on the most common path through this form.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { OfferingDetail } from "./OfferingDetail";
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
    created_by_display_name: "Maria Dela Cruz",
    ...overrides,
  };
}

function detail(overrides = {}) {
  return {
    id: 1,
    code: "WQ-BOD5",
    name: "BOD (5-day)",
    description: "",
    service_line: "water_environmental",
    test_methods: [],
    test_method_names: ["BOD"],
    turnaround_days: 5,
    is_accredited: true,
    is_active: true,
    current_price: price(),
    prices: [price()],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderDetail(offering = detail(), user = staffUser({ roles: [role("lab_supervisor")] })) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/service-offerings/1/set-price/": { body: offering },
    "/service-offerings/1/": { body: offering },
  });
  renderWithProviders(<OfferingDetail />, { route: "/catalogue/1", path: "/catalogue/:id" });
  return stub;
}

describe("OfferingDetail", () => {
  it("breaks the current price into net, VAT and gross", async () => {
    renderDetail();

    // Scoped to the Current price card: the same figures appear again in
    // the history table below, which is not what this asserts.
    const card = (await screen.findByRole("heading", { name: "Current price" })).closest("div")!;
    expect(within(card).getByText("₱1,000.00 excl. VAT")).toBeInTheDocument();
    expect(within(card).getByText("₱120.00")).toBeInTheDocument();
    expect(within(card).getByText("₱1,120.00")).toBeInTheDocument();
  });

  it("supersedes rather than edits: it posts a new price", async () => {
    const { calls } = renderDetail();
    await screen.findByRole("button", { name: "Supersede price" });

    await userEvent.type(screen.getByLabelText("Amount"), "1200.00");
    await userEvent.click(screen.getByRole("button", { name: "Supersede price" }));

    await waitFor(() => {
      const posted = calls.find((c) => c.method === "POST" && c.url.includes("/set-price/"));
      expect(posted).toBeTruthy();
      expect(posted!.body).toMatchObject({ amount: "1200.00", vat_treatment: "exclusive", vat_rate_pct: "12.00" });
    });
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("omits the effective date when it is left blank", async () => {
    // "" is not a date; the server defaults to today when the field is absent.
    const { calls } = renderDetail();
    await screen.findByRole("button", { name: "Supersede price" });

    await userEvent.type(screen.getByLabelText("Amount"), "1200.00");
    await userEvent.click(screen.getByRole("button", { name: "Supersede price" }));

    await waitFor(() => {
      const posted = calls.find((c) => c.method === "POST" && c.url.includes("/set-price/"));
      expect(posted).toBeTruthy();
      expect(posted!.body).not.toHaveProperty("effective_from");
    });
  });

  it("sends a back-dated price when one is given", async () => {
    const { calls } = renderDetail();
    await screen.findByRole("button", { name: "Supersede price" });

    await userEvent.type(screen.getByLabelText("Amount"), "900.00");
    await userEvent.type(screen.getByLabelText("Effective from"), "2026-03-01");
    await userEvent.click(screen.getByRole("button", { name: "Supersede price" }));

    await waitFor(() => {
      const posted = calls.find((c) => c.method === "POST" && c.url.includes("/set-price/"));
      expect(posted!.body).toMatchObject({ effective_from: "2026-03-01" });
    });
  });

  it("shows the history with the superseded window", async () => {
    renderDetail(
      detail({
        prices: [
          price({ id: 2, amount: "1200.00", effective_from: "2026-07-01", net_amount: "1200.00", gross_amount: "1344.00" }),
          price({ id: 1, effective_to: "2026-06-30" }),
        ],
      }),
    );

    expect(await screen.findByText("2026-06-30")).toBeInTheDocument();
    expect(screen.getByText("current")).toBeInTheDocument();
  });

  it("names the role a reader is missing instead of hiding the panel", async () => {
    renderDetail(detail(), staffUser({ roles: [role("analyst")] }));

    expect(await screen.findByText(/requires role: lab_supervisor or system_administrator/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supersede price" })).not.toBeInTheDocument();
  });

  it("says an unpriced offering is unpriced", async () => {
    renderDetail(detail({ current_price: null, prices: [] }));

    expect(await screen.findByText(/not priced today/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set price" })).toBeInTheDocument();
  });
});
