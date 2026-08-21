/**
 * My Credit Notes: a customer redeeming their own credit.
 *
 * A CreditNote is money the lab already holds — issued automatically when
 * check_session_capacity cancels an under-subscribed session, so the funds
 * stay with the customer rather than going back as a refund. Redeeming one
 * moves it against an enrollment, which makes the client-side guards here
 * the customer-facing half of the same rules the Staff Console's Training
 * screen enforces.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MyCreditNotes } from "./MyCreditNotes";
import { customerUser, renderWithProviders, stubApi } from "../test/helpers";

function note(overrides = {}) {
  return {
    id: 8,
    amount: "1750.50",
    status: "available",
    created_at: "2026-08-01T09:00:00Z",
    ...overrides,
  };
}

function listOf(...results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

function render(notes = [note()], extra = {}) {
  const stub = stubApi({
    "/auth/customer/me": { body: customerUser() },
    "/my/credit-notes/": { body: listOf(...notes) },
    ...extra,
  });
  renderWithProviders(<MyCreditNotes />, { route: "/my-credit-notes", path: "/my-credit-notes" });
  return stub;
}

describe("the list", () => {
  it("shows the amount and status of each note", async () => {
    render();

    expect(await screen.findByText("₱1750.50")).toBeInTheDocument();
    expect(screen.getByText("available")).toBeInTheDocument();
  });

  it("explains the empty state", async () => {
    render([]);

    expect(await screen.findByText("No credit notes on your account.")).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/credit-notes/": { status: 500, body: { detail: "boom" } },
    });
    renderWithProviders(<MyCreditNotes />, { route: "/my-credit-notes", path: "/my-credit-notes" });

    expect(await screen.findByText("Couldn't load your credit notes.")).toBeInTheDocument();
  });
});

describe("redeeming", () => {
  it("posts the enrollment the customer entered", async () => {
    const { calls } = render([note()], {
      "POST /my/credit-notes/8/apply/": { body: note({ status: "applied" }) },
    });
    await screen.findByText("₱1750.50");

    await userEvent.type(screen.getByPlaceholderText("Enrollment ID"), "42");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.url.includes("/my/credit-notes/8/apply/"));
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toEqual({ enrollment: 42 });
  });

  it("does nothing when no enrollment has been entered", async () => {
    // Guards against posting enrollment: NaN, which the server rejects with
    // a message that tells the customer nothing useful.
    const { calls } = render();
    await screen.findByText("₱1750.50");

    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(calls.some((c) => c.url.includes("/apply/"))).toBe(false);
  });

  it("offers no control for a note that has already been applied", async () => {
    // The funds are committed; re-applying is what the server's own
    // CreditNote.apply validation refuses.
    render([note({ status: "applied" })]);
    await screen.findByText("₱1750.50");

    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Enrollment ID")).not.toBeInTheDocument();
  });

  it("keeps each row's entry separate", async () => {
    // Two available notes share one component; a single shared input would
    // let a customer type against one row and redeem the other.
    const { calls } = render([note({ id: 8, amount: "1750.50" }), note({ id: 9, amount: "900.00" })], {
      "POST /my/credit-notes/9/apply/": { body: note({ id: 9, status: "applied" }) },
    });
    await screen.findByText("₱900.00");

    const inputs = screen.getAllByPlaceholderText("Enrollment ID");
    await userEvent.type(inputs[1], "77");
    await userEvent.click(screen.getAllByRole("button", { name: "Apply" })[1]);

    const post = await waitFor(() => {
      const c = calls.find((c) => c.url.includes("/apply/"));
      expect(c).toBeTruthy();
      return c!;
    });
    // The second row's note, with the second row's value.
    expect(post.url).toContain("/my/credit-notes/9/apply/");
    expect(post.body).toEqual({ enrollment: 77 });
    expect((inputs[0] as HTMLInputElement).value).toBe("");
  });

  it("surfaces the server's refusal", async () => {
    render([note()], {
      "POST /my/credit-notes/8/apply/": {
        status: 400,
        body: { detail: "That enrollment does not belong to you." },
      },
    });
    await screen.findByText("₱1750.50");

    await userEvent.type(screen.getByPlaceholderText("Enrollment ID"), "42");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(await screen.findByText("That enrollment does not belong to you.")).toBeInTheDocument();
  });
});
