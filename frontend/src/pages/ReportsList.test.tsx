/**
 * Reports screen.
 *
 * The behaviour worth pinning is the asynchronous half. Generation is a
 * background job, so a row's status changes with no user action, and the two
 * ways that goes wrong are both invisible to the backend suite: offering a
 * Download button for a report that has no file behind it yet, and rendering
 * a presigned URL at render time so it has expired by the time it's clicked.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReportsList } from "./ReportsList";
import { renderWithProviders, staffUser, stubApi } from "../test/helpers";
import type { Report } from "../api/types";

function report(overrides: Partial<Report> = {}): Report {
  return {
    id: 1,
    sample: 5,
    sample_code: "WE-2026-0042",
    order: null,
    report_type: "water_environmental_coa",
    file_id: "",
    status: "pending",
    failure_reason: "",
    generated_at: "2026-08-19T02:00:00Z",
    generated_by: 1,
    generated_by_display_name: "R. Santos",
    version: 1,
    ...overrides,
  };
}

function page(rows: Report[]) {
  return { count: rows.length, next: null, previous: null, results: rows };
}

function renderReports(rows: Report[], extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: staffUser() },
    "/reports/": { body: page(rows) },
    ...extra,
  });
  renderWithProviders(<ReportsList />, { route: "/reports", path: "/reports" });
  return stub;
}

async function rowFor(code: string) {
  // findBy, not getBy: the table only exists once the reports query resolves.
  const cell = await screen.findByText(code);
  return cell.closest("tr") as HTMLElement;
}

describe("download availability", () => {
  it("disables Download while a report is still generating", async () => {
    renderReports([report({ status: "generating" })]);

    const button = await screen.findByRole("button", { name: "Download" });

    // There is no file behind the row yet -- the endpoint would answer 409.
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Not available while the report is 'generating'.");
  });

  it("enables Download once the report is ready", async () => {
    renderReports([report({ status: "ready", file_id: "reports/x/1-v1.pdf" })]);

    const button = await screen.findByRole("button", { name: "Download" });

    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("title");
  });

  it("keeps Download disabled for a failed report and shows why", async () => {
    renderReports([
      report({ status: "failed", failure_reason: "ReportTemplateMissing: no template 'custom.html'" }),
    ]);

    expect(await screen.findByRole("button", { name: "Download" })).toBeDisabled();
    // The reason has to reach the screen, or a failure is only diagnosable
    // by reading worker logs.
    expect(screen.getByText(/ReportTemplateMissing/)).toBeInTheDocument();
  });
});

describe("fetching the document", () => {
  it("requests the presigned URL at click time, not at render time", async () => {
    // The URL expires (15 min by default), so one written into an href when
    // the table rendered is a link that quietly stops working while the page
    // is open.
    const { calls } = renderReports([report({ status: "ready" })], {
      "/reports/1/download/": { body: { url: "https://oss.example/x.pdf", expires_in: 900 } },
    });
    const open = vi.fn();
    vi.stubGlobal("open", open);

    await screen.findByRole("button", { name: "Download" });
    expect(calls.some((c) => c.url.includes("/download/"))).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Download" }));

    await waitFor(() => expect(open).toHaveBeenCalledWith("https://oss.example/x.pdf", "_blank", "noopener,noreferrer"));
  });

  it("surfaces the server's reason when the link cannot be produced", async () => {
    renderReports([report({ status: "ready" })], {
      "/reports/1/download/": { status: 502, body: { detail: "Could not produce a download link: timeout" } },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Download" }));

    expect(await screen.findByText(/Could not produce a download link/)).toBeInTheDocument();
  });
});

describe("the table", () => {
  it("shows the sample code, type, version and who generated it", async () => {
    renderReports([report({ status: "ready", version: 2 })]);

    const row = within(await rowFor("WE-2026-0042"));
    expect(row.getByText("Water/Environmental COA")).toBeInTheDocument();
    expect(row.getByText("v2")).toBeInTheDocument();
    expect(row.getByText("R. Santos")).toBeInTheDocument();
    expect(row.getByText("Ready")).toBeInTheDocument();
  });

  it("links a report back to its sample", async () => {
    renderReports([report()]);

    const link = await screen.findByRole("link", { name: "WE-2026-0042" });

    expect(link).toHaveAttribute("href", "/samples/5");
  });

  it("explains where reports come from when there are none", async () => {
    renderReports([]);

    // An empty Reports screen is otherwise a dead end: creation lives on the
    // approved sample, not here.
    expect(await screen.findByText(/Generate one from an approved sample/)).toBeInTheDocument();
  });

  it("asks the API for the chosen status rather than filtering client-side", async () => {
    const { calls } = renderReports([report({ status: "ready" })]);
    await screen.findByRole("button", { name: "Download" });

    await userEvent.selectOptions(screen.getByRole("combobox"), "failed");

    // Same class of bug the Review Queue and Testing Queue both surfaced: a
    // filter that looks right but never reaches the query string.
    await waitFor(() => expect(calls.some((c) => c.url.includes("status=failed"))).toBe(true));
  });
});
