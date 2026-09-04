/**
 * Accepting a quotation.
 *
 * The only place in this portal where a customer commits to money, so the
 * things that must hold are about not letting that happen by accident or
 * in ignorance:
 *
 * - **the terms sit next to the button** — the total including VAT, and
 *   the date the offer lapses;
 * - **a lapsed offer cannot be accepted**, and the page decides that from
 *   the date rather than the stored status, because the lab's nightly
 *   sweep can lag a lapse by up to a day;
 * - **an answered quotation offers no buttons at all**, and says what was
 *   decided instead.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { QuotationDetail } from "./QuotationDetail";
import { customerUser, renderWithProviders, stubApi } from "../test/helpers";

function line(overrides = {}) {
  return {
    id: 1,
    offering_code: "WQ-POT",
    offering_name: "Potability panel",
    quantity: 4,
    discount_pct: "0.00",
    unit_amount: "5600.00",
    currency: "PHP",
    vat_treatment: "exclusive",
    vat_rate_pct: "12.00",
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
    service_line: "water_environmental",
    status: "sent",
    valid_until: "2026-12-31",
    notes: "",
    item_count: 1,
    totals: { net: "22400.00", vat: "2688.00", gross: "25088.00", currency: "PHP" },
    is_expired: false,
    sent_at: "2026-08-01T09:00:00Z",
    decided_at: null,
    created_at: "2026-08-01T09:00:00Z",
    items: [line()],
    order: null,
    ...overrides,
  };
}

function renderQuotation(data = quotation()) {
  const stub = stubApi({
    "/auth/customer/me": { body: customerUser() },
    "/my/quotations/9/accept/": { body: { ...data, status: "accepted", order: 77 } },
    "/my/quotations/9/decline/": { body: { ...data, status: "declined" } },
    "/my/quotations/9/": { body: data },
  });
  renderWithProviders(<QuotationDetail />, { route: "/quotations/9", path: "/quotations/:id" });
  return stub;
}

describe("QuotationDetail", () => {
  it("states the total and the lapse date beside the accept button", async () => {
    renderQuotation();

    const answer = (await screen.findByRole("button", { name: /accept this quotation/i })).closest("div")!
      .parentElement!;
    expect(within(answer).getByText(/₱25,088.00/)).toBeInTheDocument();
    expect(within(answer).getByText(/lapses on 2026-12-31/i)).toBeInTheDocument();
  });

  it("shows each quoted line with how its rate was quoted", async () => {
    renderQuotation({
      ...quotation(),
      items: [line(), line({ id: 2, offering_name: "SEM / EDS", vat_treatment: "inclusive" })],
    });

    expect(await screen.findByText("+ VAT")).toBeInTheDocument();
    expect(screen.getByText("incl. VAT")).toBeInTheDocument();
  });

  it("posts an accept rather than setting a status", async () => {
    const { calls } = renderQuotation();
    await screen.findByRole("button", { name: /accept this quotation/i });

    await userEvent.click(screen.getByRole("button", { name: /accept this quotation/i }));

    await waitFor(() => {
      const posted = calls.find((c) => c.method === "POST");
      expect(posted!.url).toContain("/my/quotations/9/accept/");
    });
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("offers no answer on an offer that has lapsed", async () => {
    // Stored as sent, past its date: the sweep runs nightly, so the date
    // is what decides.
    renderQuotation(quotation({ is_expired: true }));

    expect(await screen.findByText(/lapsed on 2026-12-31/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /accept this quotation/i })).not.toBeInTheDocument();
  });

  it("says what was decided once it has been answered", async () => {
    renderQuotation(quotation({ status: "accepted", decided_at: "2026-08-05T09:00:00Z", order: 77 }));

    expect(await screen.findByText(/you accepted this quotation/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /order #77/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^decline$/i })).not.toBeInTheDocument();
  });

  it("shows the lab's terms when there are any", async () => {
    renderQuotation(quotation({ notes: "Sampling by the client. Results in 10 working days." }));

    expect(await screen.findByText(/sampling by the client/i)).toBeInTheDocument();
  });

  it("surfaces the server's refusal rather than failing silently", async () => {
    stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/quotations/9/accept/": { status: 400, body: { detail: "Q-2026-00009 expired on 2026-08-31." } },
      "/my/quotations/9/": { body: quotation() },
    });
    renderWithProviders(<QuotationDetail />, { route: "/quotations/9", path: "/quotations/:id" });

    await userEvent.click(await screen.findByRole("button", { name: /accept this quotation/i }));

    expect(await screen.findByText(/expired on 2026-08-31/i)).toBeInTheDocument();
  });
});
