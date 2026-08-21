/**
 * My Reports: the customer-facing download flow.
 *
 * The behaviour worth pinning is that the presigned URL is fetched when the
 * customer clicks, not when the page loads. Those URLs expire (15 minutes by
 * default), so a version that rendered hrefs up front would hand out links
 * that silently fail on a tab left open — a bug that never shows up in a
 * quick manual test and always shows up in support tickets.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MyReports } from "./MyReports";
import { customerUser, renderWithProviders, stubApi } from "../test/helpers";

const REPORT = {
  id: 7,
  sample: 3,
  sample_code: "WE-2026-0042",
  order: null,
  report_type: "water_environmental_coa",
  status: "ready",
  generated_at: "2026-08-01T09:00:00Z",
  version: 1,
};

function listOf(...results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

let assign: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // jsdom's window.location.assign is not implemented and logs a "Not
  // implemented: navigation" error; replace it so the click is observable.
  assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("listing", () => {
  it("shows a readable report type and its sample code", async () => {
    stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/reports/": { body: listOf(REPORT) },
    });

    renderWithProviders(<MyReports />, { route: "/reports", path: "/reports" });

    expect(await screen.findByText("Certificate of Analysis — Water/Environmental")).toBeInTheDocument();
    expect(screen.getByText("WE-2026-0042")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
  });

  it("explains the empty state rather than showing a bare table", async () => {
    stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/reports/": { body: listOf() },
    });

    renderWithProviders(<MyReports />, { route: "/reports", path: "/reports" });

    expect(await screen.findByText(/No reports yet/)).toBeInTheDocument();
  });

  it("surfaces a load failure", async () => {
    stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/reports/": { status: 500, body: { detail: "boom" } },
    });

    renderWithProviders(<MyReports />, { route: "/reports", path: "/reports" });

    expect(await screen.findByText("Couldn't load your reports.")).toBeInTheDocument();
  });
});

describe("download", () => {
  it("does not request a URL until the customer clicks", async () => {
    const { calls } = stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/reports/": { body: listOf(REPORT) },
      "/my/reports/7/download/": { body: { url: "https://oss.example/x.pdf", expires_in: 900 } },
    });

    renderWithProviders(<MyReports />, { route: "/reports", path: "/reports" });
    await screen.findByRole("button", { name: "Download PDF" });

    // The whole point: no presigned URL is minted on load, so none can go
    // stale before it is used.
    expect(calls.some((c) => c.url.includes("/download/"))).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Download PDF" }));

    await waitFor(() => expect(calls.some((c) => c.url.includes("/my/reports/7/download/"))).toBe(true));
  });

  it("navigates to the presigned URL the server returns", async () => {
    stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/reports/": { body: listOf(REPORT) },
      "/my/reports/7/download/": {
        body: { url: "https://oss.example/reports/coa-7-v1.pdf?sig=abc", expires_in: 900 },
      },
    });

    renderWithProviders(<MyReports />, { route: "/reports", path: "/reports" });
    await userEvent.click(await screen.findByRole("button", { name: "Download PDF" }));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://oss.example/reports/coa-7-v1.pdf?sig=abc"),
    );
  });

  it("reports a download failure against the row instead of navigating", async () => {
    stubApi({
      "/auth/customer/me": { body: customerUser() },
      "/my/reports/": { body: listOf(REPORT) },
      "/my/reports/7/download/": { status: 502, body: { detail: "Could not produce a download link." } },
    });

    renderWithProviders(<MyReports />, { route: "/reports", path: "/reports" });
    await userEvent.click(await screen.findByRole("button", { name: "Download PDF" }));

    expect(await screen.findByText("Could not produce a download link.")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });
});
