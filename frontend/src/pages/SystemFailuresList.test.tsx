/**
 * The system failure register screen (ISO/IEC 17025:2017 7.11.3(e)).
 *
 * The clause has two halves and the screen has to keep them apart: what the
 * system did by itself is a fact on display, what a person did is a box
 * somebody has to fill in — and a failure with that box empty cannot be
 * closed. The server enforces that; these tests pin that the screen does not
 * offer an action the server will refuse, which is the failure mode that
 * turns a guard into a confusing error message.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SystemFailuresList } from "./SystemFailuresList";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function failure(overrides = {}) {
  return {
    id: 7,
    component: "object_storage",
    component_display: "Object storage",
    severity: "degraded",
    summary: "retention archival skipped: object storage is not configured",
    detail: "Report#12: OSS_ENDPOINT is not set",
    immediate_action: "retry_scheduled",
    immediate_action_display: "Left unprocessed for the next run to retry",
    occurrences: 4,
    first_seen_at: "2026-08-20T02:00:00Z",
    last_seen_at: "2026-08-24T02:00:00Z",
    status: "open",
    acknowledged_by: null,
    acknowledged_by_display_name: null,
    acknowledged_at: null,
    corrective_action: "",
    investigation: null,
    closed_by: null,
    closed_by_display_name: null,
    closed_at: null,
    ...overrides,
  };
}

function render(user = staffUser({ roles: [role("qa_officer")] }), rows = [failure()], extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/system-failures/": { body: { count: rows.length, results: rows } },
    ...extra,
  });
  renderWithProviders(<SystemFailuresList />, { route: "/system-failures", path: "/system-failures" });
  return stub;
}

describe("the register", () => {
  it("lists a failure with its occurrence count rather than one row per occurrence", async () => {
    render();

    expect(await screen.findByText("Object storage")).toBeInTheDocument();
    expect(screen.getByText("retention archival skipped: object storage is not configured")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("opens on what still needs attention rather than on everything ever", async () => {
    const stub = render();
    await screen.findByText("Object storage");

    const listCall = stub.calls.find((c) => c.url.includes("/system-failures/"));
    expect(listCall!.url).toContain("status=open%2Cacknowledged");
  });

  it("says so when nothing matches instead of showing an empty table", async () => {
    render(staffUser({ roles: [role("qa_officer")] }), []);

    expect(await screen.findByText("No system failures match this filter.")).toBeInTheDocument();
  });
});

describe("the two halves of the clause", () => {
  it("shows what the system did as a fact, with no way to edit it", async () => {
    render();
    await userEvent.click(await screen.findByText("Object storage"));

    expect(screen.getByText("Left unprocessed for the next run to retry")).toBeInTheDocument();
    // The immediate action is display text, never a form control.
    expect(screen.queryByRole("textbox", { name: /immediate action/i })).not.toBeInTheDocument();
  });

  it("offers an empty corrective action box for a person to fill in", async () => {
    render();
    await userEvent.click(await screen.findByText("Object storage"));

    expect(screen.getByLabelText("Corrective action")).toHaveValue("");
  });
});

describe("the write gate", () => {
  it("hides the actions from an analyst and says who does record them", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await userEvent.click(await screen.findByText("Object storage"));

    expect(screen.queryByRole("button", { name: "Close failure" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(screen.getByText("A QA Officer or Lab Supervisor records the corrective action.")).toBeInTheDocument();
  });

  it("shows them to a QA officer", async () => {
    render();
    await userEvent.click(await screen.findByText("Object storage"));

    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close failure" })).toBeInTheDocument();
  });
});

describe("closing", () => {
  it("will not offer to close while the corrective action is empty", async () => {
    render();
    await userEvent.click(await screen.findByText("Object storage"));

    expect(screen.getByRole("button", { name: "Close failure" })).toBeDisabled();
  });

  it("stays disabled for whitespace, which the server would reject too", async () => {
    render();
    await userEvent.click(await screen.findByText("Object storage"));
    await userEvent.type(screen.getByLabelText("Corrective action"), "   ");

    expect(screen.getByRole("button", { name: "Close failure" })).toBeDisabled();
  });

  it("sends the corrective action with the close, in one request", async () => {
    const stub = render(staffUser({ roles: [role("qa_officer")] }), [failure()], {
      "POST /system-failures/7/close/": { body: failure({ status: "closed", corrective_action: "Endpoint corrected." }) },
    });
    await userEvent.click(await screen.findByText("Object storage"));
    await userEvent.type(screen.getByLabelText("Corrective action"), "Endpoint corrected.");
    await userEvent.click(screen.getByRole("button", { name: "Close failure" }));

    await waitFor(() => {
      const closeCall = stub.calls.find((c) => c.url.includes("/close/"));
      expect(closeCall).toBeDefined();
      expect(closeCall!.body).toEqual({ corrective_action: "Endpoint corrected." });
    });
  });

  it("acknowledging is its own act, separate from recording an action", async () => {
    const stub = render(staffUser({ roles: [role("qa_officer")] }), [failure()], {
      "POST /system-failures/7/acknowledge/": { body: failure({ status: "acknowledged" }) },
    });
    await userEvent.click(await screen.findByText("Object storage"));
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));

    await waitFor(() => {
      expect(stub.calls.some((c) => c.url.includes("/acknowledge/"))).toBe(true);
    });
  });

  it("shows a closed failure's corrective action as a record rather than a form", async () => {
    render(staffUser({ roles: [role("qa_officer")] }), [
      failure({ status: "closed", corrective_action: "Credentials rotated.", closed_by_display_name: "QA Officer" }),
    ]);
    await userEvent.click(await screen.findByText("Object storage"));

    expect(screen.getByText("Credentials rotated.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Corrective action")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close failure" })).not.toBeInTheDocument();
  });
});
