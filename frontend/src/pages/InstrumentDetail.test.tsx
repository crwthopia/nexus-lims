/**
 * Instrument detail: logging a calibration.
 *
 * FR-E3-02 makes this more than a form. Recording a calibration result
 * flips Instrument.status server-side — a `fail` puts the instrument into
 * out_of_calibration — and advances calibration_due_date. The screen
 * therefore must not assume what it wrote; it has to re-read the instrument,
 * or an analyst is looking at "In Service" on a unit the lab has just taken
 * out of service, which is the one thing this record exists to prevent.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { InstrumentDetail } from "./InstrumentDetail";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function instrument(overrides = {}) {
  return {
    id: 5,
    name: "ICP-MS Unit A",
    model: "xrf",
    status: "in_service",
    calibration_due_date: "2026-12-01",
    custodian: null,
    custodian_display_name: null,
    parent_instrument: null,
    // The detail endpoint always includes this; the component reads
    // .length on it unguarded, so omitting it crashes the render.
    child_instruments: [],
    ...overrides,
  };
}

const RECORD = {
  id: 1,
  instrument: 5,
  instrument_name: "ICP-MS Unit A",
  performed_by: 1,
  performed_by_display_name: "R. Santos",
  performed_at: "2026-08-01T09:00:00Z",
  result: "pass",
  next_due_date: "2027-08-01",
};

function listOf(...results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

function render(user = staffUser({ roles: [role("instrument_custodian")] }), inst = instrument(), extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/instruments/5/": { body: inst },
    "/calibration-records/": { body: listOf(RECORD) },
    ...extra,
  });
  renderWithProviders(<InstrumentDetail />, { route: "/equipment/instruments/5", path: "/equipment/instruments/:id" });
  return stub;
}

describe("the calibration form's role gate", () => {
  it("is hidden from an analyst", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText("ICP-MS Unit A");

    expect(screen.queryByRole("button", { name: "Log calibration" })).not.toBeInTheDocument();
  });

  it("is shown to an instrument custodian", async () => {
    render();

    expect(await screen.findByRole("button", { name: "Log calibration" })).toBeInTheDocument();
  });

  it("is shown to a lab supervisor", async () => {
    render(staffUser({ roles: [role("lab_supervisor")] }));

    expect(await screen.findByRole("button", { name: "Log calibration" })).toBeInTheDocument();
  });

  it("stays available on an out-of-calibration instrument", async () => {
    // Deliberately not gated on status: logging a passing calibration is
    // exactly how an out_of_calibration instrument returns to service.
    render(undefined, instrument({ status: "out_of_calibration" }));

    expect(await screen.findByRole("button", { name: "Log calibration" })).toBeInTheDocument();
  });
});

describe("logging a calibration", () => {
  it("sends the result and next due date against this instrument", async () => {
    const { calls } = render(undefined, undefined, {
      "POST /calibration-records/": { status: 201, body: RECORD },
    });
    await screen.findByRole("button", { name: "Log calibration" });

    await userEvent.selectOptions(screen.getByLabelText("Result"), "fail");
    await userEvent.type(screen.getByLabelText("Next due date"), "2027-01-15");
    await userEvent.click(screen.getByRole("button", { name: "Log calibration" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toMatchObject({ instrument: 5, result: "fail", next_due_date: "2027-01-15" });
    // performed_at is stamped by the client at submit time rather than left
    // to the server, so the record reflects when the work was done.
    expect(post.body).toHaveProperty("performed_at");
  });

  it("re-reads the instrument afterwards rather than assuming its status", async () => {
    // FR-E3-02: a failed calibration flips the instrument to
    // out_of_calibration server-side. Showing a stale "In Service" on a unit
    // the lab just pulled is the failure this guards.
    const { calls } = render(undefined, undefined, {
      "POST /calibration-records/": { status: 201, body: { ...RECORD, result: "fail" } },
    });
    await screen.findByRole("button", { name: "Log calibration" });
    const readsBefore = calls.filter((c) => c.method === "GET" && c.url.includes("/instruments/5/")).length;

    await userEvent.type(screen.getByLabelText("Next due date"), "2027-01-15");
    await userEvent.click(screen.getByRole("button", { name: "Log calibration" }));

    await waitFor(() => {
      const readsAfter = calls.filter((c) => c.method === "GET" && c.url.includes("/instruments/5/")).length;
      expect(readsAfter).toBeGreaterThan(readsBefore);
    });
  });

  it("surfaces the server's rejection", async () => {
    render(undefined, undefined, {
      "POST /calibration-records/": {
        status: 400,
        body: { detail: "next_due_date must be in the future." },
      },
    });
    await screen.findByRole("button", { name: "Log calibration" });

    await userEvent.type(screen.getByLabelText("Next due date"), "2020-01-01");
    await userEvent.click(screen.getByRole("button", { name: "Log calibration" }));

    expect(await screen.findByText("next_due_date must be in the future.")).toBeInTheDocument();
  });
});

describe("the instrument view", () => {
  it("shows the current status and calibration due date", async () => {
    // The pair a custodian is here to check.
    render(undefined, instrument({ status: "out_of_calibration" }));

    expect(await screen.findByText("Out of Calibration")).toBeInTheDocument();
    expect(screen.getByText("2026-12-01")).toBeInTheDocument();
  });

  it("lists who performed each calibration", async () => {
    render();
    await screen.findByText("ICP-MS Unit A");

    // Exact name: "Log calibration" also matches a loose /Calibration/i.
    const heading = screen.getByRole("heading", { name: "Calibration history" });
    const card = heading.closest(".card") as HTMLElement;
    expect(within(card).getByText("R. Santos")).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser() },
      "/instruments/5/": { status: 500, body: { detail: "boom" } },
      "/calibration-records/": { body: listOf() },
    });
    renderWithProviders(<InstrumentDetail />, {
      route: "/equipment/instruments/5",
      path: "/equipment/instruments/:id",
    });

    expect(await screen.findByText("Couldn't load this instrument.")).toBeInTheDocument();
  });
});
