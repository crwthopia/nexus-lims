/**
 * Training: the write gate, and the credit-note apply control.
 *
 * The credit-note behaviour is the substance. A CreditNote is money the lab
 * already holds — issued automatically when check_session_capacity cancels
 * an under-subscribed session — and applying one moves it against an
 * enrollment. The rules that matter are that an already-applied note offers
 * no control at all, and that a server refusal (wrong customer, already
 * applied) reaches the operator rather than failing silently.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TrainingList } from "./TrainingList";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

const COURSE = { id: 1, title: "ISO 17025 Awareness", cpd_units: "8.0", price: "5000.00" };
const SESSION = {
  id: 3,
  course: 1,
  course_title: "ISO 17025 Awareness",
  start_date: "2026-09-01",
  end_date: "2026-09-02",
  capacity: 20,
  min_capacity: 5,
  cancellation_threshold_days: 7,
  status: "scheduled",
  confirmed_enrollment_count: 4,
};
const AVAILABLE_NOTE = { id: 8, amount: "1750.50", status: "available", created_at: "2026-08-01T09:00:00Z" };
const APPLIED_NOTE = { id: 9, amount: "3000.00", status: "applied", created_at: "2026-07-01T09:00:00Z" };

function listOf(...results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

function render(user = staffUser(), extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/training-courses/": { body: listOf(COURSE) },
    "/training-sessions/": { body: listOf(SESSION) },
    "/credit-notes/": { body: listOf(AVAILABLE_NOTE) },
    ...extra,
  });
  renderWithProviders(<TrainingList />, { route: "/training", path: "/training" });
  return stub;
}

describe("the write gate", () => {
  it("hides the course and session forms from an analyst", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText("₱1750.50");

    expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  });

  it("shows them to a training coordinator", async () => {
    render(staffUser({ roles: [role("training_coordinator")] }));
    await screen.findByText("₱1750.50");

    // Two forms: courses and sessions.
    expect(await screen.findAllByRole("button", { name: "Add" })).toHaveLength(2);
  });

  it("hides the apply control from a user who cannot write", async () => {
    // Credit notes are money; offering the control to someone the server
    // will refuse only produces a confusing 403.
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText("₱1750.50");

    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
  });
});

describe("creating a course", () => {
  it("sends the CPD units and price", async () => {
    const { calls } = render(staffUser({ roles: [role("training_coordinator")] }), {
      "POST /training-courses/": { status: 201, body: COURSE },
    });
    await screen.findByText("₱1750.50");

    await userEvent.type(screen.getByLabelText("New course title"), "Method Validation");
    await userEvent.type(screen.getByLabelText("CPD units"), "4");
    await userEvent.type(screen.getByLabelText("Price (PHP)"), "3500");
    await userEvent.click(screen.getAllByRole("button", { name: "Add" })[0]);

    const post = await waitFor(() => {
      const c = calls.find((c) => c.url.includes("/training-courses/") && c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toEqual({ title: "Method Validation", cpd_units: "4", price: "3500" });
  });
});

describe("applying a credit note", () => {
  it("posts the enrollment the operator typed", async () => {
    const { calls } = render(staffUser({ roles: [role("training_coordinator")] }), {
      "POST /credit-notes/8/apply/": { body: { ...AVAILABLE_NOTE, status: "applied" } },
    });
    await screen.findByText("₱1750.50");

    await userEvent.type(screen.getByPlaceholderText("Enrollment ID"), "42");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.url.includes("/credit-notes/8/apply/"));
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toEqual({ enrollment: 42 });
  });

  it("does nothing when no enrollment has been entered", async () => {
    // Guards against posting `enrollment: NaN`, which the server would
    // reject with a validation error that says nothing useful.
    const { calls } = render(staffUser({ roles: [role("training_coordinator")] }));
    await screen.findByText("₱1750.50");

    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(calls.some((c) => c.url.includes("/apply/"))).toBe(false);
  });

  it("offers no control for a note that has already been applied", async () => {
    // The funds are already committed; re-applying is what the server's own
    // CreditNote.apply validation refuses.
    render(staffUser({ roles: [role("training_coordinator")] }), {
      "/credit-notes/": { body: listOf(APPLIED_NOTE) },
    });
    await screen.findByText("₱3000.00");

    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Enrollment ID")).not.toBeInTheDocument();
  });

  it("surfaces the server's refusal", async () => {
    render(staffUser({ roles: [role("training_coordinator")] }), {
      "POST /credit-notes/8/apply/": {
        status: 400,
        body: { detail: "That enrollment belongs to a different customer." },
      },
    });
    await screen.findByText("₱1750.50");

    await userEvent.type(screen.getByPlaceholderText("Enrollment ID"), "42");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(
      await screen.findByText("That enrollment belongs to a different customer."),
    ).toBeInTheDocument();
  });
});

describe("the lists", () => {
  it("shows a session's confirmed count against its minimum", async () => {
    // The pair is what tells a coordinator whether
    // check_session_capacity is about to cancel the session.
    render();

    // The title appears in both the catalog and the session row, so assert
    // on the pair of elements rather than a single ambiguous match.
    expect(await screen.findAllByText("ISO 17025 Awareness")).toHaveLength(2);
    // Rendered as "confirmed / capacity" -- the pair that tells a coordinator
    // whether check_session_capacity is about to cancel the session.
    expect(screen.getByText(/4\s*\/\s*20/)).toBeInTheDocument();
  });

  it("says so when no credit notes exist", async () => {
    render(staffUser(), { "/credit-notes/": { body: listOf() } });

    expect(await screen.findByText("No credit notes issued yet.")).toBeInTheDocument();
  });
});
