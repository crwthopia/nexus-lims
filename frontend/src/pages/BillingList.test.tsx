/**
 * Billing: the invoice write form's role gate and the status filter.
 *
 * BILLING_WRITE_ROLES in api/types.ts is a hand-maintained copy of the
 * server's own list (its comment says so), which makes it exactly the kind
 * of constant that drifts silently. The tests below pin the roles this
 * screen actually honours, so a divergence shows up here rather than as a
 * 403 in front of a user who was shown the form.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { BillingList } from "./BillingList";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

const INVOICE = {
  id: 4,
  order: 2,
  enrollment: null,
  customer_email: "client@example.test",
  amount: "15000.00",
  currency: "PHP",
  status: "issued",
  created_at: "2026-08-01T09:00:00Z",
};

function listOf(...results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

function render(user = staffUser(), extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/invoices/": { body: listOf(INVOICE) },
    ...extra,
  });
  renderWithProviders(<BillingList />, { route: "/billing", path: "/billing" });
  return stub;
}

describe("the invoice form's role gate", () => {
  it("is hidden from a user without a billing write role", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText("client@example.test");

    // Visible-but-disabled would be wrong here: unlike an FSM action, an
    // analyst is never going to be able to raise an invoice, so showing the
    // form only advertises something they cannot do.
    expect(screen.queryByRole("button", { name: "Create invoice" })).not.toBeInTheDocument();
  });

  it("is shown to a lab supervisor", async () => {
    render(staffUser({ roles: [role("lab_supervisor")] }));

    expect(await screen.findByRole("button", { name: "Create invoice" })).toBeInTheDocument();
  });

  it("is shown to a training coordinator, who bills enrollments", async () => {
    render(staffUser({ roles: [role("training_coordinator")] }));

    expect(await screen.findByRole("button", { name: "Create invoice" })).toBeInTheDocument();
  });

  it("is hidden from an approver, whose authority is over results not money", async () => {
    render(staffUser({ roles: [role("approver"), role("reviewer"), role("qa_officer")] }));
    await screen.findByText("client@example.test");

    expect(screen.queryByRole("button", { name: "Create invoice" })).not.toBeInTheDocument();
  });
});

describe("creating an invoice", () => {
  it("bills an order by default", async () => {
    const { calls } = render(staffUser({ roles: [role("lab_supervisor")] }), {
      "POST /invoices/": { status: 201, body: { ...INVOICE, id: 9 } },
    });
    await screen.findByRole("button", { name: "Create invoice" });

    await userEvent.type(screen.getByLabelText("Order ID"), "2");
    await userEvent.type(screen.getByLabelText("Amount (PHP)"), "15000");
    await userEvent.click(screen.getByRole("button", { name: "Create invoice" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toEqual({ order: 2, amount: "15000" });
  });

  it("bills an enrollment instead when the target is switched", async () => {
    // An Invoice references exactly one of order/enrollment, never both --
    // sending both would violate the server's own constraint.
    const { calls } = render(staffUser({ roles: [role("lab_supervisor")] }), {
      "POST /invoices/": { status: 201, body: { ...INVOICE, id: 9 } },
    });
    await screen.findByRole("button", { name: "Create invoice" });

    await userEvent.selectOptions(screen.getByLabelText("Bill against"), "enrollment");
    await userEvent.type(screen.getByLabelText("Enrollment ID"), "5");
    await userEvent.type(screen.getByLabelText("Amount (PHP)"), "3000");
    await userEvent.click(screen.getByRole("button", { name: "Create invoice" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toEqual({ enrollment: 5, amount: "3000" });
    expect(post.body).not.toHaveProperty("order");
  });

  it("surfaces the server's rejection", async () => {
    render(staffUser({ roles: [role("lab_supervisor")] }), {
      "POST /invoices/": { status: 400, body: { detail: "An invoice already exists for this order." } },
    });
    await screen.findByRole("button", { name: "Create invoice" });

    await userEvent.type(screen.getByLabelText("Order ID"), "2");
    await userEvent.type(screen.getByLabelText("Amount (PHP)"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Create invoice" }));

    expect(await screen.findByText("An invoice already exists for this order.")).toBeInTheDocument();
  });
});

describe("the status filter", () => {
  it("sends the selected status to the API", async () => {
    // The same class of bug the Review Queue and Testing Queue both
    // surfaced server-side: a filter control that doesn't filter.
    const { calls } = render();
    await screen.findByText("client@example.test");

    await userEvent.selectOptions(screen.getByRole("combobox"), "paid");

    await waitFor(() => expect(calls.some((c) => c.url.includes("/invoices/?status=paid"))).toBe(true));
  });

  it("requests the unfiltered list by default", async () => {
    const { calls } = render();
    await screen.findByText("client@example.test");

    const first = calls.find((c) => c.url.includes("/invoices/"));
    expect(first?.url).not.toContain("status=");
  });
});

describe("the list", () => {
  it("says so when a filter matches nothing, rather than showing an empty table", async () => {
    stubApi({ "/auth/staff/me": { body: staffUser() }, "/invoices/": { body: listOf() } });
    renderWithProviders(<BillingList />, { route: "/billing", path: "/billing" });

    expect(await screen.findByText("No invoices match this filter.")).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser() },
      "/invoices/": { status: 500, body: { detail: "boom" } },
    });
    renderWithProviders(<BillingList />, { route: "/billing", path: "/billing" });

    expect(await screen.findByText("Couldn't load invoices.")).toBeInTheDocument();
  });
});
