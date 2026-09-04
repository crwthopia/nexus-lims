/**
 * The dashboard.
 *
 * What has to hold here is honesty, not layout:
 *
 * - the money is **list price**, and the screen says so. A future reader
 *   relabelling it "revenue" is the failure this guards against, because
 *   nothing in the database supports that word yet;
 * - **unattributed requests are visible**. Requests on methods that belong
 *   to no offering, or to several, are excluded from the ranking; if the
 *   screen didn't say so, the list would look complete when it is not;
 * - **ranking by value re-asks the server**, because it changes which
 *   offerings make the top eight — sorting the same eight client-side would
 *   quietly drop a low-volume, high-value offering off the card.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Dashboard } from "./Dashboard";
import { renderWithProviders, staffUser, stubApi } from "../test/helpers";

function dashboardData(overrides = {}) {
  return {
    rank: "volume",
    window: { from: "2026-06-07", to: "2026-09-04", days: 90, previous_from: "2026-03-09", previous_to: "2026-06-06" },
    totals: { samples_received: 412, test_requests: 1183, list_value_net: "1874500.00", currency: "PHP" },
    previous_totals: { samples_received: 366, test_requests: 1042, list_value_net: "1612000.00" },
    leading_analyses: [
      {
        offering_id: 1,
        code: "WQ-POT",
        name: "Potability panel",
        service_line: "water_environmental",
        request_count: 264,
        list_value_net: "492800.00",
      },
    ],
    leading_analyses_other: { offering_count: 0, request_count: 0, list_value_net: "0.00" },
    unattributed_requests: { no_offering: 0, ambiguous: 0, unpriced: 0 },
    service_line_mix: [
      { service_line: "water_environmental", label: "Water / Environmental Testing", sample_count: 291 },
      { service_line: "failure_analysis", label: "Failure Analysis", sample_count: 121 },
    ],
    monthly: [
      { month: "2026-07", request_count: 402, list_value_net: "651200.00" },
      { month: "2026-08", request_count: 421, list_value_net: "689400.00" },
    ],
    turnaround: {
      sample_count: 388,
      median_days: 4.2,
      p90_days: 9.6,
      by_service_line: [
        { service_line: "water_environmental", sample_count: 276, median_days: 3.4, p90_days: 7.1 },
      ],
    },
    quality: {
      results_entered: 2140,
      out_of_spec: 71,
      out_of_spec_pct: 3.3,
      open_investigations: 4,
      samples_awaiting_review: 17,
      instruments_out_of_calibration: 1,
      open_system_failures: 0,
    },
    ...overrides,
  };
}

function renderDashboard(data = dashboardData()) {
  const stub = stubApi({
    "/auth/staff/me": { body: staffUser() },
    "/analytics/dashboard/": { body: data },
  });
  renderWithProviders(<Dashboard />, { route: "/dashboard", path: "/dashboard" });
  return stub;
}

describe("Dashboard", () => {
  it("calls the money list price, never revenue", async () => {
    renderDashboard();

    expect(await screen.findByText("List-price value")).toBeInTheDocument();
    expect(screen.getByText("₱1,874,500.00")).toBeInTheDocument();
    expect(screen.getByText(/net of VAT, at the rate in force/i)).toBeInTheDocument();
    expect(screen.queryByText(/revenue/i)).not.toBeInTheDocument();
  });

  it("compares against the preceding period of equal length", async () => {
    renderDashboard();

    // 412 vs 366 = +12.6%, shown as a direction and a magnitude.
    expect(await screen.findByText("13%")).toBeInTheDocument();
    expect(screen.getAllByText(/on the previous period/i).length).toBeGreaterThan(0);
  });

  it("draws no comparison when the previous period had nothing to compare with", async () => {
    // A "+100%" against zero is arithmetic, not information.
    renderDashboard(
      dashboardData({ previous_totals: { samples_received: 0, test_requests: 0, list_value_net: "0.00" } }),
    );

    await screen.findByText("List-price value");
    expect(screen.queryByText(/on the previous period/i)).not.toBeInTheDocument();
  });

  it("says how many requests the ranking leaves out, and why", async () => {
    renderDashboard(dashboardData({ unattributed_requests: { no_offering: 62, ambiguous: 20, unpriced: 3 } }));

    const note = await screen.findByText(/85 requests above the ranking isn't counted/i);
    expect(note).toHaveTextContent("62 on methods in no offering");
    expect(note).toHaveTextContent("20 on methods sold under more than one");
    expect(note).toHaveTextContent("3 on offerings with no price that day");
  });

  it("stays quiet when every request could be attributed", async () => {
    renderDashboard();

    await screen.findByText("Leading analyses");
    expect(screen.queryByText(/isn't counted against any offering/i)).not.toBeInTheDocument();
  });

  it("re-asks the server when the ranking changes", async () => {
    // Not a client-side re-sort: ranking by value changes which offerings
    // make the list at all, and the tail is folded server-side.
    const { calls } = renderDashboard();
    await screen.findByText("Leading analyses");

    await userEvent.selectOptions(screen.getByLabelText("Rank leading analyses by"), "value");

    await waitFor(() => expect(calls.some((c) => c.url.includes("rank=value"))).toBe(true));
  });

  it("sends the reporting period as a from-date", async () => {
    const { calls } = renderDashboard();
    await screen.findByText("Leading analyses");

    await userEvent.selectOptions(screen.getByLabelText("Reporting period"), "30");

    await waitFor(() => expect(calls.filter((c) => c.url.includes("from=")).length).toBeGreaterThan(1));
  });

  it("labels the service-line mix rather than relying on colour", async () => {
    renderDashboard();

    // The same name appears in the turnaround card, so scope to the legend.
    const legend = await screen.findByRole("img", { name: /samples by service line/i });
    const entry = within(legend.parentElement!).getByText("Water / Environmental").closest("li")!;
    expect(within(entry).getByText(/291 · 71%/)).toBeInTheDocument();
  });

  it("says nothing was approved rather than showing a zero turnaround", async () => {
    renderDashboard(
      dashboardData({ turnaround: { sample_count: 0, median_days: null, p90_days: null, by_service_line: [] } }),
    );

    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.getByText(/nothing approved in this period/i)).toBeInTheDocument();
  });

  it("separates the period's rates from the queues as they stand now", async () => {
    renderDashboard();

    expect(await screen.findByText(/out-of-spec is for the period; the queues are where things stand now/i)).toBeInTheDocument();
    expect(screen.getByText("3.3% of 2,140")).toBeInTheDocument();
  });
});
