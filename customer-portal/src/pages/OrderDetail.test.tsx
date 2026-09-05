/**
 * The customer's own order.
 *
 * The page a customer is most likely to check against their own records,
 * so the things that have to hold are about money being unambiguous:
 *
 * - **every line says how its rate was quoted.** NASAT publishes some
 *   rates VAT-exclusive and some VAT-inclusive, and a column of figures
 *   where that differs silently invites the wrong comparison;
 * - **the totals come from the server**, not from adding the column up
 *   here — a net line added to a gross one is wrong by 12%;
 * - **"not yet invoiced" is shown**, because a customer looking at an
 *   order wants to know what is still coming.
 */

import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OrderDetail } from "./OrderDetail";
import { renderWithProviders, stubApi, customerUser } from "../test/helpers";

function line(overrides = {}) {
  return {
    id: 1,
    offering_code: "WQ-BOD5",
    offering_name: "BOD (5-day)",
    quantity: 2,
    discount_pct: "0.00",
    unit_amount: "1200.00",
    currency: "PHP",
    vat_treatment: "exclusive",
    vat_rate_pct: "12.00",
    line_amount: "2400.00",
    net_amount: "2400.00",
    vat_amount: "288.00",
    gross_amount: "2688.00",
    is_invoiced: false,
    ...overrides,
  };
}

function order(overrides = {}) {
  return {
    id: 1204,
    customer: 1,
    service_line: "water_environmental",
    status: "in_progress",
    created_at: "2026-07-01T00:00:00Z",
    items: [line()],
    totals: { net: "2400.00", vat: "288.00", gross: "2688.00", currency: "PHP" },
    invoices: [],
    ...overrides,
  };
}

function renderOrder(data = order()) {
  stubApi({
    "/auth/customer/me": { body: customerUser() },
    "/my/orders/1204/": { body: data },
  });
  return renderWithProviders(<OrderDetail />, { route: "/orders/1204", path: "/orders/:id" });
}

describe("OrderDetail", () => {
  it("shows each line with its rate and what it comes to", async () => {
    renderOrder();

    const row = (await screen.findByText("BOD (5-day)")).closest("tr")!;
    expect(within(row).getByText(/₱1,200.00/)).toBeInTheDocument();
    expect(within(row).getByText("₱2,400.00")).toBeInTheDocument();
    expect(within(row).getByText("₱2,688.00")).toBeInTheDocument();
  });

  it("says how each rate was quoted", async () => {
    renderOrder(
      order({
        items: [line(), line({ id: 2, offering_name: "SEM / EDS", vat_treatment: "inclusive" })],
      }),
    );

    expect(await screen.findByText("+ VAT")).toBeInTheDocument();
    expect(screen.getByText("incl. VAT")).toBeInTheDocument();
  });

  it("uses the server's totals rather than adding the column up", async () => {
    // The stub's totals deliberately differ from the single line: if the
    // page were summing locally this would show 2,688.
    renderOrder(order({ totals: { net: "9999.00", vat: "1199.88", gross: "11198.88", currency: "PHP" } }));

    expect(await screen.findByText(/Total ₱11,198.88/)).toBeInTheDocument();
  });

  it("says so instead of totalling an order priced in two currencies", async () => {
    renderOrder(order({ totals: { net: "0.00", vat: "0.00", gross: "0.00", currency: null } }));

    expect(await screen.findByText(/priced in more than one currency/i)).toBeInTheDocument();
  });

  it("tells the customer what is still to come", async () => {
    renderOrder(order({ items: [line({ is_invoiced: true }), line({ id: 2, is_invoiced: false })] }));

    expect(await screen.findByText("Invoiced")).toBeInTheDocument();
    expect(screen.getByText("Not yet invoiced")).toBeInTheDocument();
  });

  it("lists the invoices raised against the order", async () => {
    renderOrder(
      order({
        invoices: [
          { id: 44, amount: "2688.00", currency: "PHP", status: "unpaid", created_at: "2026-08-01T09:00:00Z" },
        ],
      }),
    );

    const row = (await screen.findByText("#44")).closest("tr")!;
    expect(within(row).getByText("₱2,688.00")).toBeInTheDocument();
    expect(within(row).getByText("Unpaid")).toBeInTheDocument();
  });

  it("says nothing has been invoiced rather than showing an empty table", async () => {
    renderOrder();

    expect(await screen.findByText(/nothing has been invoiced yet/i)).toBeInTheDocument();
  });
});
