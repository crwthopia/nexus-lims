/**
 * Invoice detail: recording a payment.
 *
 * This is the screen where money is reconciled by hand (Blueprint 3.7,
 * Phase 1 has no gateway integration), so the interesting behaviours are
 * the two gates on the form and what the form actually sends. A confirmed
 * payment flips the parent Invoice to `paid` server-side, which is why the
 * mutation invalidates the invoice rather than patching state locally --
 * the new status is the server's to decide.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { InvoiceDetail } from "./InvoiceDetail";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

const PAYMENT = {
  id: 1,
  invoice: 4,
  method: "bank_transfer",
  reference_number: "BT-99123",
  recorded_by: 1,
  recorded_by_display_name: "R. Santos",
  status: "confirmed",
  paid_at: "2026-08-02T10:00:00Z",
  notes: "Deposit slip on file",
};

function invoice(overrides = {}) {
  return {
    id: 4,
    order: 2,
    enrollment: null,
    customer_email: "client@example.test",
    amount: "15000.00",
    currency: "PHP",
    status: "issued",
    created_at: "2026-08-01T09:00:00Z",
    payments: [],
    ...overrides,
  };
}

function render(user = staffUser({ roles: [role("lab_supervisor")] }), inv = invoice(), extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/invoices/4/": { body: inv },
    ...extra,
  });
  renderWithProviders(<InvoiceDetail />, { route: "/invoices/4", path: "/invoices/:id" });
  return stub;
}

describe("the payment form's gates", () => {
  it("is hidden from a user without a billing write role", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText(/Invoice #4/);

    expect(screen.queryByRole("button", { name: "Record payment" })).not.toBeInTheDocument();
  });

  it("is shown to a lab supervisor", async () => {
    render();

    expect(await screen.findByRole("button", { name: "Record payment" })).toBeInTheDocument();
  });

  it("is hidden on a void invoice even for a user who may otherwise write", async () => {
    // A voided invoice is not owed, so recording money against it would
    // reconcile a debt that no longer exists.
    render(staffUser({ roles: [role("lab_supervisor")] }), invoice({ status: "void" }));
    await screen.findByText(/Invoice #4/);

    expect(screen.queryByRole("button", { name: "Record payment" })).not.toBeInTheDocument();
  });

  it("stays available on an already-paid invoice", async () => {
    // Deliberately not gated: a reversal or a correcting entry against a
    // paid invoice is a normal reconciliation action.
    render(staffUser({ roles: [role("lab_supervisor")] }), invoice({ status: "paid" }));

    expect(await screen.findByRole("button", { name: "Record payment" })).toBeInTheDocument();
  });
});

describe("recording a payment", () => {
  it("sends the method and status the operator chose", async () => {
    const { calls } = render(undefined, undefined, {
      "POST /invoices/4/payments/": { status: 201, body: PAYMENT },
    });
    await screen.findByRole("button", { name: "Record payment" });

    await userEvent.selectOptions(screen.getByLabelText("Method"), "cash");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "pending_confirmation");
    await userEvent.click(screen.getByRole("button", { name: "Record payment" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toMatchObject({ method: "cash", status: "pending_confirmation" });
  });

  it("omits reference_number and notes rather than sending empty strings", async () => {
    // Both are optional on the server. An empty string is a *supplied*
    // blank reference, which is not the same as not having one -- it would
    // land in the record as a payment whose reference is deliberately "".
    const { calls } = render(undefined, undefined, {
      "POST /invoices/4/payments/": { status: 201, body: PAYMENT },
    });
    await screen.findByRole("button", { name: "Record payment" });

    await userEvent.click(screen.getByRole("button", { name: "Record payment" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).not.toHaveProperty("reference_number");
    expect(post.body).not.toHaveProperty("notes");
  });

  it("sends a reference number when one is given", async () => {
    const { calls } = render(undefined, undefined, {
      "POST /invoices/4/payments/": { status: 201, body: PAYMENT },
    });
    await screen.findByRole("button", { name: "Record payment" });

    await userEvent.type(screen.getByLabelText("Reference number"), "BT-99123");
    await userEvent.type(screen.getByLabelText("Notes"), "Deposit slip on file");
    await userEvent.click(screen.getByRole("button", { name: "Record payment" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toMatchObject({
      reference_number: "BT-99123",
      notes: "Deposit slip on file",
    });
  });

  it("re-reads the invoice afterwards rather than assuming the new status", async () => {
    // Recording a confirmed Payment flips Invoice.status to `paid`
    // server-side. The screen has to ask rather than guess, or it shows a
    // stale status until the next navigation.
    const { calls } = render(undefined, undefined, {
      "POST /invoices/4/payments/": { status: 201, body: PAYMENT },
    });
    await screen.findByRole("button", { name: "Record payment" });
    const readsBefore = calls.filter((c) => c.method === "GET" && c.url.includes("/invoices/4/")).length;

    await userEvent.click(screen.getByRole("button", { name: "Record payment" }));

    await waitFor(() => {
      const readsAfter = calls.filter((c) => c.method === "GET" && c.url.includes("/invoices/4/")).length;
      expect(readsAfter).toBeGreaterThan(readsBefore);
    });
  });

  it("surfaces the server's rejection", async () => {
    render(undefined, undefined, {
      "POST /invoices/4/payments/": {
        status: 400,
        body: { detail: "Cannot record a payment against a void invoice." },
      },
    });
    await screen.findByRole("button", { name: "Record payment" });

    await userEvent.click(screen.getByRole("button", { name: "Record payment" }));

    expect(
      await screen.findByText("Cannot record a payment against a void invoice."),
    ).toBeInTheDocument();
  });
});

describe("the payments list", () => {
  it("shows who recorded each payment", async () => {
    // Manual reconciliation is an attributable act: who entered it is the
    // audit question this table has to answer.
    render(undefined, invoice({ payments: [PAYMENT] }));
    await screen.findByText("R. Santos");

    // Scoped to the Payments card: the method and status labels also appear
    // as <option>s in the record-a-payment form, so an unscoped query
    // matches twice and would pass even if the table rendered nothing.
    const table = screen.getByRole("heading", { name: "Payments" }).closest(".card") as HTMLElement;

    expect(within(table).getByText("R. Santos")).toBeInTheDocument();
    expect(within(table).getByText("BT-99123")).toBeInTheDocument();
    expect(within(table).getByText("Bank Transfer")).toBeInTheDocument();
    expect(within(table).getByText("Confirmed")).toBeInTheDocument();
  });

  it("says so when nothing has been recorded", async () => {
    render();

    expect(await screen.findByText("No payments recorded yet.")).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser() },
      "/invoices/4/": { status: 500, body: { detail: "boom" } },
    });
    renderWithProviders(<InvoiceDetail />, { route: "/invoices/4", path: "/invoices/:id" });

    expect(await screen.findByText("Couldn't load this invoice.")).toBeInTheDocument();
  });
});
