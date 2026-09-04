/**
 * The order screen.
 *
 * Two rules, both about money:
 *
 * - **The client never sends a price.** The form posts an offering, a
 *   quantity and a discount; the server snapshots the rate in force. A
 *   price field here would be a way to sell at any figure someone typed,
 *   and the whole rate card would be decoration.
 * - **Invoicing bills the unbilled remainder**, and the button says how
 *   many lines that is. An order part-billed in March and finished in July
 *   gets a second invoice for the July work, not a duplicate of March's —
 *   and a button that hid that would invite a second click.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { OrderDetail } from "./OrderDetail";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function item(overrides = {}) {
  return {
    id: 1,
    order: 1,
    offering: 7,
    offering_code: "WQ-BOD5",
    offering_name: "BOD (5-day)",
    quantity: 2,
    discount_pct: "0.00",
    unit_amount: "1200.00",
    currency: "PHP",
    vat_treatment: "exclusive",
    vat_rate_pct: "12.00",
    source_price: 3,
    line_amount: "2400.00",
    net_amount: "2400.00",
    vat_amount: "288.00",
    gross_amount: "2688.00",
    is_invoiced: false,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function order(overrides = {}) {
  return {
    id: 1,
    customer: 5,
    service_line: "water_environmental",
    status: "in_progress",
    item_count: 1,
    items: [item()],
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

const CATALOGUE = {
  count: 1,
  next: null,
  previous: null,
  results: [
    {
      id: 7,
      code: "WQ-BOD5",
      name: "BOD (5-day)",
      description: "",
      service_line: "water_environmental",
      test_methods: [],
      test_method_names: [],
      turnaround_days: 5,
      is_accredited: true,
      is_active: true,
      current_price: {
        id: 3,
        offering: 7,
        amount: "1200.00",
        currency: "PHP",
        vat_treatment: "exclusive",
        vat_rate_pct: "12.00",
        effective_from: "2026-01-01",
        effective_to: null,
        note: "",
        net_amount: "1200.00",
        vat_amount: "144.00",
        gross_amount: "1344.00",
        is_current: true,
        created_at: "2026-01-01T00:00:00Z",
        created_by: null,
        created_by_display_name: null,
      },
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  ],
};

function renderOrder(data = order(), user = staffUser({ roles: [role("sample_receiver"), role("lab_supervisor")] })) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/orders/1/items/": { body: item({ id: 2 }) },
    "/orders/1/invoice/": { body: { id: 44, lines: [], payments: [] } },
    "/orders/1/": { body: data },
    "/service-offerings/": { body: CATALOGUE },
  });
  renderWithProviders(<OrderDetail />, { route: "/orders/1", path: "/orders/:id" });
  return stub;
}

describe("OrderDetail", () => {
  it("shows the snapshotted rate and how it was quoted", async () => {
    renderOrder();

    const row = (await screen.findByText("WQ-BOD5")).closest("tr")!;
    expect(within(row).getByText(/₱1,200.00/)).toBeInTheDocument();
    expect(within(row).getByText("excl.")).toBeInTheDocument();
    expect(within(row).getByText("₱2,688.00")).toBeInTheDocument();
  });

  it("posts an offering and a quantity, never a price", async () => {
    const { calls } = renderOrder();
    await screen.findByRole("button", { name: "Add line" });

    await userEvent.selectOptions(screen.getByLabelText("Offering"), "7");
    await userEvent.clear(screen.getByLabelText("Quantity"));
    await userEvent.type(screen.getByLabelText("Quantity"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Add line" }));

    await waitFor(() => {
      const posted = calls.find((c) => c.method === "POST" && c.url.includes("/items/"));
      expect(posted).toBeTruthy();
      expect(posted!.body).toMatchObject({ offering: 7, quantity: 3 });
      expect(posted!.body).not.toHaveProperty("unit_amount");
    });
  });

  it("says how many lines the invoice button will bill", async () => {
    renderOrder(order({ items: [item(), item({ id: 2, is_invoiced: true })] }));

    expect(await screen.findByRole("button", { name: "Invoice 1 line" })).toBeInTheDocument();
  });

  it("offers nothing to invoice once every line is billed", async () => {
    renderOrder(order({ items: [item({ is_invoiced: true })] }));

    const button = await screen.findByRole("button", { name: "Fully invoiced" });
    expect(button).toBeDisabled();
  });

  it("marks the lines that have been billed", async () => {
    renderOrder(order({ items: [item({ is_invoiced: true })] }));

    expect(await screen.findByText("Invoiced")).toBeInTheDocument();
  });

  it("hides the line form from a role that cannot order", async () => {
    renderOrder(order(), staffUser({ roles: [role("analyst")] }));

    await screen.findByText("WQ-BOD5");
    expect(screen.queryByRole("button", { name: "Add line" })).not.toBeInTheDocument();
  });

  it("hides the invoice button from a role that cannot bill", async () => {
    renderOrder(order(), staffUser({ roles: [role("sample_receiver")] }));

    await screen.findByRole("button", { name: "Add line" });
    expect(screen.queryByRole("button", { name: /invoice/i })).not.toBeInTheDocument();
  });

  it("totals the order net, VAT and gross", async () => {
    renderOrder();

    expect(await screen.findByText(/Gross ₱2,688.00/)).toBeInTheDocument();
    expect(screen.getByText(/Net ₱2,400.00/)).toBeInTheDocument();
  });
});
