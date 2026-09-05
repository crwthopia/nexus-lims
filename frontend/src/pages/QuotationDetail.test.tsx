/**
 * The console's quotation screen.
 *
 * What has to hold is the immutability rule, expressed in the UI rather
 * than only in the API: **a draft is a form, a sent quotation is a
 * document.** A screen that kept the line form after sending and let the
 * server refuse the save would teach the operator the rule the hard way,
 * one failed click at a time.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { QuotationDetail } from "./QuotationDetail";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function line(overrides = {}) {
  return {
    id: 1,
    quotation: 9,
    offering: 7,
    offering_code: "WQ-POT",
    offering_name: "Potability panel",
    quantity: 4,
    discount_pct: "0.00",
    unit_amount: "5600.00",
    currency: "PHP",
    vat_treatment: "exclusive",
    vat_rate_pct: "12.00",
    source_price: 3,
    line_amount: "22400.00",
    net_amount: "22400.00",
    vat_amount: "2688.00",
    gross_amount: "25088.00",
    ...overrides,
  };
}

function quotation(overrides = {}) {
  return {
    id: 9,
    reference: "Q-2026-00009",
    customer: 5,
    customer_email: "procurement@acme.test",
    service_line: "water_environmental",
    order: null,
    supersedes: null,
    status: "draft",
    valid_until: "2026-12-31",
    notes: "",
    item_count: 1,
    totals: { net: "22400.00", vat: "2688.00", gross: "25088.00", currency: "PHP" },
    is_expired: false,
    sent_at: null,
    decided_at: null,
    prepared_by: 1,
    prepared_by_display_name: "Maria Dela Cruz",
    created_at: "2026-08-01T09:00:00Z",
    items: [line()],
    ...overrides,
  };
}

function renderQuotation(data = quotation(), user = staffUser({ roles: [role("lab_supervisor")] })) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/quotations/9/items/": { body: line({ id: 2 }) },
    "/quotations/9/send/": { body: { ...data, status: "sent" } },
    "/quotations/9/accept/": { body: { ...data, status: "accepted", order: 77 } },
    "/quotations/9/revise/": { body: { ...quotation(), id: 12, supersedes: 9 } },
    "/quotations/9/": { body: data },
    "/service-offerings/": { body: { count: 0, next: null, previous: null, results: [] } },
  });
  renderWithProviders(<QuotationDetail />, { route: "/quotations/9", path: "/quotations/:id" });
  return stub;
}

describe("QuotationDetail", () => {
  it("lets a draft be built and sent", async () => {
    renderQuotation();

    expect(await screen.findByRole("button", { name: "Add line" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send to procurement@acme.test/i })).toBeInTheDocument();
  });

  it("will not send an empty quotation", async () => {
    renderQuotation(quotation({ items: [], item_count: 0 }));

    const send = await screen.findByRole("button", { name: /send to/i });
    expect(send).toBeDisabled();
  });

  it("takes the line form away once the quotation is sent", async () => {
    // The immutability rule, made visible rather than enforced by a
    // failed request.
    renderQuotation(quotation({ status: "sent" }));

    await screen.findByText("What is being quoted");
    expect(screen.queryByRole("button", { name: "Add line" })).not.toBeInTheDocument();
  });

  it("offers both answers on a sent quotation, for the ones that arrive by email", async () => {
    renderQuotation(quotation({ status: "sent" }));

    expect(await screen.findByRole("button", { name: "Record acceptance" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record decline" })).toBeInTheDocument();
  });

  it("will not accept an offer that has lapsed", async () => {
    renderQuotation(quotation({ status: "sent", is_expired: true }));

    expect(await screen.findByRole("button", { name: "Record acceptance" })).toBeDisabled();
    expect(screen.getByText("lapsed")).toBeInTheDocument();
  });

  it("posts the transition rather than patching a status", async () => {
    const { calls } = renderQuotation();
    await screen.findByRole("button", { name: /send to/i });

    await userEvent.click(screen.getByRole("button", { name: /send to/i }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.includes("/send/"))).toBe(true));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("points at the order an accepted quotation became", async () => {
    renderQuotation(quotation({ status: "accepted", order: 77 }));

    expect(await screen.findByRole("link", { name: /order #77/i })).toBeInTheDocument();
  });

  it("offers a revision on anything already sent", async () => {
    renderQuotation(quotation({ status: "declined" }));

    expect(await screen.findByRole("button", { name: /revise into a new quotation/i })).toBeInTheDocument();
  });

  it("names the role a reader is missing rather than hiding the panel", async () => {
    renderQuotation(quotation(), staffUser({ roles: [role("analyst")] }));

    expect(await screen.findByText(/requires role: sample_receiver or/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send to/i })).not.toBeInTheDocument();
  });
});
