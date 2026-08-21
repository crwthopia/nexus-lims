/**
 * Equipment: the instrument/reagent write gate and the instrument status
 * filter.
 *
 * EQUIPMENT_WRITE_ROLES is another hand-maintained mirror of a server-side
 * list, and a narrow one — instrument custodian or lab supervisor, nobody
 * else. The status filter matters because `out_of_calibration` is the
 * status FR-E3-02 flips an instrument into automatically; being unable to
 * filter for it is being unable to answer "what needs recalibrating".
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { EquipmentList } from "./EquipmentList";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

const INSTRUMENT = {
  id: 1,
  name: "ICP-MS Unit A",
  model: "xrf",
  status: "in_service",
  calibration_due_date: "2026-12-01",
  custodian: null,
  custodian_display_name: null,
  parent_instrument: null,
};

const REAGENT = {
  id: 1,
  name: "Lead standard",
  lot_number: "L-2026-04",
  crm_traceability_reference: "NIST-1643f",
  expiry_date: "2027-01-01",
  status: "active",
};

function listOf(...results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

function render(user = staffUser(), extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/instruments/": { body: listOf(INSTRUMENT) },
    "/standard-reagents/": { body: listOf(REAGENT) },
    ...extra,
  });
  renderWithProviders(<EquipmentList />, { route: "/equipment", path: "/equipment" });
  return stub;
}

describe("the write gate", () => {
  it("hides both forms from an analyst", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText("ICP-MS Unit A");

    expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  });

  it("shows them to an instrument custodian", async () => {
    render(staffUser({ roles: [role("instrument_custodian")] }));
    await screen.findByText("ICP-MS Unit A");

    // Two forms on this screen: instruments and standard reagents.
    expect(await screen.findAllByRole("button", { name: "Add" })).toHaveLength(2);
  });

  it("shows them to a lab supervisor", async () => {
    render(staffUser({ roles: [role("lab_supervisor")] }));
    await screen.findByText("ICP-MS Unit A");

    expect(await screen.findAllByRole("button", { name: "Add" })).toHaveLength(2);
  });

  it("hides them from a QA officer, who authorises retests but does not own equipment", async () => {
    render(staffUser({ roles: [role("qa_officer")] }));
    await screen.findByText("ICP-MS Unit A");

    expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  });
});

describe("the instrument status filter", () => {
  it("asks the API for out-of-calibration instruments", async () => {
    // FR-E3-02 flips an instrument to out_of_calibration automatically when
    // a calibration fails, so this filter is how the lab finds them.
    const { calls } = render();
    await screen.findByText("ICP-MS Unit A");

    await userEvent.selectOptions(screen.getAllByRole("combobox")[0], "out_of_calibration");

    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/instruments/?status=out_of_calibration"))).toBe(true),
    );
  });

  it("says so when nothing matches", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser() },
      "/instruments/": { body: listOf() },
      "/standard-reagents/": { body: listOf(REAGENT) },
    });
    renderWithProviders(<EquipmentList />, { route: "/equipment", path: "/equipment" });

    expect(await screen.findByText("No instruments match this filter.")).toBeInTheDocument();
  });
});

describe("adding a standard reagent", () => {
  it("sends the CRM traceability reference and expiry the lab needs on file", async () => {
    // Both are what make a reagent usable under FR-C3-02: results may only
    // cite active, non-expired standards with traceable provenance.
    const { calls } = render(staffUser({ roles: [role("instrument_custodian")] }), {
      "POST /standard-reagents/": { status: 201, body: REAGENT },
    });
    await screen.findByText("ICP-MS Unit A");

    await userEvent.type(screen.getByLabelText("Name"), "Cadmium standard");
    await userEvent.type(screen.getByLabelText("Lot number"), "C-2026-09");
    await userEvent.type(screen.getByLabelText("CRM traceability reference"), "NIST-3108");
    await userEvent.type(screen.getByLabelText("Expiry date"), "2027-06-30");
    await userEvent.click(screen.getAllByRole("button", { name: "Add" })[1]);

    const post = await waitFor(() => {
      const c = calls.find((c) => c.url.includes("/standard-reagents/") && c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toEqual({
      name: "Cadmium standard",
      lot_number: "C-2026-09",
      crm_traceability_reference: "NIST-3108",
      expiry_date: "2027-06-30",
    });
  });
});

describe("the reagent list", () => {
  it("shows lot and expiry, which is what makes a reagent identifiable", async () => {
    render();

    expect(await screen.findByText("Lead standard")).toBeInTheDocument();
    expect(screen.getByText("L-2026-04")).toBeInTheDocument();
    expect(screen.getByText("2027-01-01")).toBeInTheDocument();
    expect(screen.getByText("NIST-1643f")).toBeInTheDocument();
  });
});
