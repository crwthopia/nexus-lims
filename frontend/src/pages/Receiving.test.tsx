/**
 * The receiving bench.
 *
 * What is worth pinning is the ISO/IEC 17025:2017 7.4.3 half, because the
 * whole reason this screen exists is that a checklist filled in afterwards
 * from memory is what that clause is written against. So: the deviations
 * box has to appear the moment a check fails, the form must not submit
 * without it, and what reaches the API has to be what the clerk actually
 * ticked — a form that quietly sent `seal_intact: true` for an unticked box
 * would be worse than no form at all.
 *
 * The scan path matters too and fails silently when it breaks: a handheld
 * scanner is a keyboard that types and presses Enter, so a screen that
 * needed a mouse click would work in every manual test and not at a bench.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Receiving } from "./Receiving";
import { renderWithProviders, role, staffUser, stubApi, stubPrinting } from "../test/helpers";
import type { Sample } from "../api/types";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function sample(overrides: Partial<Sample> = {}): Sample {
  return {
    id: 7,
    order: null,
    service_line: "water_environmental",
    priority: "routine",
    unique_sample_code: "WE-202609-0042",
    client_reference: "JOB-118",
    sampling_point: "",
    collection_datetime: null,
    container_type: "1L amber glass",
    container_count: 2,
    preservation_method: "",
    retention_period: "",
    holding_time: null,
    received_at: null,
    status: "registered",
    safety_flags: [],
    created_at: "2026-09-10T00:00:00Z",
    updated_at: "2026-09-10T00:00:00Z",
    ...overrides,
  };
}

function renderReceiving(found: Sample | null, extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": {
      body: staffUser({ roles: [role("sample_receiver")] }),
    },
    "GET /samples/?code=": {
      body: { count: found ? 1 : 0, next: null, previous: null, results: found ? [found] : [] },
    },
    ...extra,
  });
  renderWithProviders(<Receiving />, { route: "/receiving", path: "/receiving" });
  return stub;
}

async function scan(code: string) {
  const user = userEvent.setup();
  const field = await screen.findByLabelText("Sample code");
  await user.type(field, `${code}{Enter}`);
  return user;
}

describe("scanning", () => {
  it("looks a sample up when the scanner presses Enter", async () => {
    // A handheld scanner types the code and submits. No click anywhere.
    const stub = renderReceiving(sample());

    await scan("WE-202609-0042");

    expect(await screen.findByText("WE-202609-0042")).toBeInTheDocument();
    expect(stub.calls.some((c) => c.url.includes("code=WE-202609-0042"))).toBe(true);
  });

  it("says so plainly when the code is not in the system", async () => {
    renderReceiving(null);

    await scan("WE-202609-9999");

    expect(await screen.findByText(/No sample with code/)).toBeInTheDocument();
  });

  it("does not offer the receipt form for a sample that is only pre-registered", async () => {
    renderReceiving(sample({ status: "pre_registered" }));

    await scan("WE-202609-0042");

    expect(await screen.findByText(/still pre-registered/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Receive and print/ })).not.toBeInTheDocument();
  });

  it("offers printing but not receiving for a sample already received", async () => {
    renderReceiving(sample({ status: "in_testing" }), {
      "GET /samples/7/": { body: { ...sample({ status: "in_testing" }), chain_of_custody_events: [], receipt: null } },
    });

    await scan("WE-202609-0042");

    expect(await screen.findByText(/Already received/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Print 2 labels/ })).toBeInTheDocument();
  });

  it("says testing is on hold when the item arrived with an unresolved deviation", async () => {
    // The clerk who recorded the leak is the one who should be chasing the
    // customer, so the hold is said here rather than only on the sample
    // screen.
    renderReceiving(sample({ status: "received" }), {
      "GET /samples/7/": {
        body: {
          ...sample({ status: "received" }),
          chain_of_custody_events: [],
          receipt: {
            id: 1,
            sample: 7,
            received_at: "2026-09-10T02:00:00Z",
            received_by: 1,
            received_by_name: "R. Santos",
            received_from: "",
            condition_on_receipt: "leaking",
            receipt_temperature_c: null,
            temperature_conforms: null,
            seal_intact: false,
            volume_sufficient: true,
            container_conforms: true,
            preservation_conforms: true,
            labelling_legible: true,
            storage_location: "",
            deviations: "Bottle leaked in transit.",
            customer_consulted_at: null,
            consultation_outcome: "",
            customer_authorised_despite_deviation: false,
            report_disclaimer_required: false,
            disclaimer_text: "",
            deviation_reasons: ["the seal was not intact"],
            is_conforming: false,
            consultation_recorded: false,
            created_at: "2026-09-10T02:00:00Z",
            updated_at: "2026-09-10T02:00:00Z",
          },
        },
      },
    });

    await scan("WE-202609-0042");

    expect(await screen.findByText(/Received with deviations/)).toBeInTheDocument();
    expect(screen.getByText(/Testing is on hold/)).toBeInTheDocument();
  });
});

describe("the 7.4.3 checklist", () => {
  it("sends what was actually ticked", async () => {
    const stub = renderReceiving(sample(), {
      "POST /samples/7/receive/": { body: sample({ status: "received" }) },
    });
    const user = await scan("WE-202609-0042");

    await user.click(await screen.findByLabelText("Seal intact"));
    await user.type(screen.getByLabelText(/Deviations/), "Bottle leaked in transit.");
    await user.click(screen.getByRole("button", { name: /Receive and print/ }));

    await waitFor(() => {
      const received = stub.calls.find((c) => c.url.includes("/receive/"));
      expect(received).toBeDefined();
      const body = received!.body as Record<string, unknown>;
      // The unticked box has to travel as false. A form that sent the
      // default would put an assertion nobody made into a regulated record.
      expect(body.seal_intact).toBe(false);
      expect(body.volume_sufficient).toBe(true);
      expect(body.deviations).toBe("Bottle leaked in transit.");
    });
  });

  it("asks for deviations as soon as a check fails, and blocks until they are given", async () => {
    renderReceiving(sample());
    const user = await scan("WE-202609-0042");

    const submit = await screen.findByRole("button", { name: /Receive and print/ });
    expect(screen.queryByLabelText(/Deviations/)).not.toBeInTheDocument();
    expect(submit).toBeEnabled();

    await user.click(screen.getByLabelText("Container as specified"));

    expect(await screen.findByLabelText(/Deviations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Receive and print/ })).toBeDisabled();
  });

  it("treats a temperature excursion as a deviation", async () => {
    renderReceiving(sample());
    const user = await scan("WE-202609-0042");

    await user.selectOptions(await screen.findByLabelText(/Within specified range/), "no");

    expect(await screen.findByLabelText(/Deviations/)).toBeInTheDocument();
  });

  it("leaves temperature conformance unset by default", async () => {
    // Null means no temperature requirement applies -- not that one was
    // met. Defaulting it either way would assert something nobody checked.
    const stub = renderReceiving(sample(), {
      "POST /samples/7/receive/": { body: sample({ status: "received" }) },
    });
    const user = await scan("WE-202609-0042");

    await user.click(await screen.findByRole("button", { name: /Receive and print/ }));

    await waitFor(() => {
      const received = stub.calls.find((c) => c.url.includes("/receive/"));
      expect(received).toBeDefined();
      expect(received!.body).not.toHaveProperty("temperature_conforms");
    });
  });

  it("hides the form from someone without the receiving role", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser({ roles: [role("analyst")] }) },
      "GET /samples/?code=": {
        body: { count: 1, next: null, previous: null, results: [sample()] },
      },
    });
    renderWithProviders(<Receiving />, { route: "/receiving", path: "/receiving" });

    await scan("WE-202609-0042");

    expect(await screen.findByText(/requires the Sample Receiver/)).toBeInTheDocument();
  });
});

describe("printing", () => {
  it("prints the labels and hands the PDF to the print dialogue", async () => {
    const printing = stubPrinting();
    renderReceiving(sample({ status: "received" }), {
      "POST /samples/7/labels/": { body: "%PDF-1.7 stub", contentType: "application/pdf" },
    });
    const user = await scan("WE-202609-0042");

    await user.click(await screen.findByRole("button", { name: /Print 2 labels/ }));

    await waitFor(() => expect(printing.printed).toHaveLength(1));
  });

  it("asks why, then reprints, when the server refuses an unexplained second print", async () => {
    const printing = stubPrinting();
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("Label came off in the cold room.");

    // Two different answers from one route. stubApi reads `status` first,
    // so the counter lives there and the other getters read it after.
    let attempt = 0;
    const labelRoute = {
      get status() {
        attempt += 1;
        return attempt === 1 ? 400 : 200;
      },
      get contentType() {
        return attempt === 1 ? undefined : "application/pdf";
      },
      get body() {
        return attempt === 1
          ? { reason: "Re-printing needs a reason (ISO/IEC 17025:2017 7.4.2)." }
          : "%PDF-1.7 stub";
      },
    };

    const stub = stubApi({
      "/auth/staff/me": { body: staffUser({ roles: [role("sample_receiver")] }) },
      "GET /samples/?code=": {
        body: { count: 1, next: null, previous: null, results: [sample({ status: "received" })] },
      },
      "POST /samples/7/labels/": labelRoute,
    });
    renderWithProviders(<Receiving />, { route: "/receiving", path: "/receiving" });
    const user = await scan("WE-202609-0042");

    await user.click(await screen.findByRole("button", { name: /Print 2 labels/ }));

    await waitFor(() => expect(prompt).toHaveBeenCalled());

    // The reason the clerk typed has to reach the register, or the retry
    // has simply laundered a refusal the standard wanted explained.
    await waitFor(() => {
      const prints = stub.calls.filter((c) => c.url.includes("/labels/"));
      expect(prints).toHaveLength(2);
      expect(prints[1].body).toEqual({ reason: "Label came off in the cold room." });
    });
    await waitFor(() => expect(printing.printed).toHaveLength(1));
  });

});
