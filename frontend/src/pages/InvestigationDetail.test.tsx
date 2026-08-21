/**
 * Investigation detail: recording root cause / CAPA, and closing.
 *
 * FR-E9-01 makes `close` the only path to `closed` — the status is not
 * settable through an ordinary update — and closing stamps closed_at
 * atomically. A closed investigation is a finished regulatory record, so the
 * screen has to stop offering edits once it is closed; otherwise an operator
 * types a revised root cause into a form whose save the server will refuse.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { InvestigationDetail } from "./InvestigationDetail";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function investigation(overrides = {}) {
  return {
    id: 12,
    related_test_result: null,
    related_sample: 3,
    related_sample_code: "WE-2026-0042",
    type: "oos",
    opened_by: 1,
    opened_by_display_name: "QA Officer",
    root_cause: "",
    capa_actions: "",
    status: "open",
    opened_at: "2026-08-01T09:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function render(user = staffUser({ roles: [role("qa_officer")] }), inv = investigation(), extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/investigations/12/": { body: inv },
    ...extra,
  });
  renderWithProviders(<InvestigationDetail />, { route: "/investigations/12", path: "/investigations/:id" });
  return stub;
}

describe("the write gate", () => {
  it("hides the form and the close button from an analyst", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText("WE-2026-0042");

    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close investigation" })).not.toBeInTheDocument();
  });

  it("shows them to a QA officer", async () => {
    render();
    await screen.findByText("WE-2026-0042");

    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close investigation" })).toBeInTheDocument();
  });

  it("shows them to a lab supervisor", async () => {
    render(staffUser({ roles: [role("lab_supervisor")] }));
    await screen.findByText("WE-2026-0042");

    expect(screen.getByRole("button", { name: "Close investigation" })).toBeInTheDocument();
  });
});

describe("a closed investigation", () => {
  const closed = investigation({
    status: "closed",
    closed_at: "2026-08-05T10:00:00Z",
    root_cause: "Reagent past expiry",
    capa_actions: "Reagent log review weekly",
  });

  it("offers no edit form, even to a QA officer", async () => {
    // The record is finished. Offering a form whose save the server refuses
    // is worse than showing none.
    render(undefined, closed);
    await screen.findByText("WE-2026-0042");

    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("offers no close button and says it is closed", async () => {
    // Double-closing is exactly what the server's FSM refuses (FR-E9-01).
    render(undefined, closed);

    expect(await screen.findByText("This investigation is closed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close investigation" })).not.toBeInTheDocument();
  });

  it("still displays the recorded root cause and CAPA read-only", async () => {
    // Closed does not mean hidden: the findings are the point of the record.
    render(undefined, closed);

    expect(await screen.findByText("Reagent past expiry")).toBeInTheDocument();
    expect(screen.getByText("Reagent log review weekly")).toBeInTheDocument();
  });
});

describe("recording root cause and CAPA", () => {
  it("prefills the form from what is already recorded", async () => {
    // Loaded through an effect once the fetch resolves; without it an
    // operator editing one field silently blanks the other on save.
    render(undefined, investigation({ root_cause: "Calibration drift", capa_actions: "Recalibrate monthly" }));

    expect(await screen.findByDisplayValue("Calibration drift")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Recalibrate monthly")).toBeInTheDocument();
  });

  it("sends both fields together", async () => {
    const { calls } = render(undefined, undefined, {
      "PATCH /investigations/12/": { body: investigation({ root_cause: "Reagent past expiry" }) },
    });
    await screen.findByRole("button", { name: "Save" });

    await userEvent.type(screen.getByLabelText("Root cause"), "Reagent past expiry");
    await userEvent.type(screen.getByLabelText("Corrective and preventive actions"), "Weekly reagent log review");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const patch = await waitFor(() => {
      const c = calls.find((c) => c.method === "PATCH");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(patch.body).toEqual({
      root_cause: "Reagent past expiry",
      capa_actions: "Weekly reagent log review",
    });
    // status is never sent: FR-E9-01 makes close the only path to closed.
    expect(patch.body).not.toHaveProperty("status");
  });
});

describe("closing", () => {
  it("posts to the close action rather than patching status", async () => {
    const { calls } = render(undefined, undefined, {
      "POST /investigations/12/close/": { body: investigation({ status: "closed", closed_at: "2026-08-05T10:00:00Z" }) },
    });
    await screen.findByRole("button", { name: "Close investigation" });

    await userEvent.click(screen.getByRole("button", { name: "Close investigation" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.url).toContain("/investigations/12/close/");
  });

  it("re-reads the investigation so closed_at and status arrive from the server", async () => {
    const { calls } = render(undefined, undefined, {
      "POST /investigations/12/close/": { body: investigation({ status: "closed" }) },
    });
    await screen.findByRole("button", { name: "Close investigation" });
    const readsBefore = calls.filter((c) => c.method === "GET" && c.url.includes("/investigations/12/")).length;

    await userEvent.click(screen.getByRole("button", { name: "Close investigation" }));

    await waitFor(() => {
      const readsAfter = calls.filter((c) => c.method === "GET" && c.url.includes("/investigations/12/")).length;
      expect(readsAfter).toBeGreaterThan(readsBefore);
    });
  });

  it("surfaces the server's refusal", async () => {
    render(undefined, undefined, {
      "POST /investigations/12/close/": {
        status: 400,
        body: { detail: "An investigation cannot be closed without a root cause." },
      },
    });
    await screen.findByRole("button", { name: "Close investigation" });

    await userEvent.click(screen.getByRole("button", { name: "Close investigation" }));

    expect(
      await screen.findByText("An investigation cannot be closed without a root cause."),
    ).toBeInTheDocument();
  });
});

describe("loading", () => {
  it("surfaces a load failure", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser() },
      "/investigations/12/": { status: 500, body: { detail: "boom" } },
    });
    renderWithProviders(<InvestigationDetail />, { route: "/investigations/12", path: "/investigations/:id" });

    expect(await screen.findByText("Couldn't load this investigation.")).toBeInTheDocument();
  });
});
