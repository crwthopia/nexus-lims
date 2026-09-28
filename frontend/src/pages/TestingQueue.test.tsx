/**
 * Testing Queue.
 *
 * What is worth pinning here is the holding-time half, because all of it
 * fails silently. A deadline rendered without saying what it was counted
 * from is a date an analyst will read as authoritative when it is a
 * fallback; an overdue row that looks like any other is a breach nobody
 * sees; and a queue that re-sorted client-side would disagree with the
 * sweep chasing the same deadlines (apps/notifications/tasks.
 * sweep_holding_times) without either side erroring.
 */

import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TestingQueue } from "./TestingQueue";
import { renderWithProviders, staffUser, stubApi } from "../test/helpers";
import type { TestRequest } from "../api/types";

function testRequest(overrides: Partial<TestRequest> = {}): TestRequest {
  return {
    id: 1,
    sample: 5,
    sample_code: "WE-202609-0042",
    sample_priority: "routine",
    test_method: 3,
    test_method_name: "Total Coliform",
    status: "assigned",
    due_at: null,
    due_at_basis: "",
    is_overdue: false,
    assigned_analyst: null,
    assigned_analyst_display_name: null,
    assigned_instrument: null,
    created_at: "2026-09-10T02:00:00Z",
    ...overrides,
  };
}

function renderQueue(rows: TestRequest[]) {
  stubApi({
    "/auth/staff/me": { body: staffUser() },
    "/test-requests/": { body: { count: rows.length, next: null, previous: null, results: rows } },
  });
  renderWithProviders(<TestingQueue />, { route: "/testing", path: "/testing" });
}

async function rowFor(code: string) {
  const cell = await screen.findByText(code);
  return cell.closest("tr") as HTMLElement;
}

describe("holding-time deadlines", () => {
  it("says what a deadline was counted from", async () => {
    renderQueue([
      testRequest({ due_at: "2026-09-11T02:00:00Z", due_at_basis: "receipt" }),
    ]);

    const row = await rowFor("WE-202609-0042");

    // A receipt-based deadline is optimistic -- the real clock started when
    // the sample was taken, which nobody recorded.
    expect(within(row).getByText("from receipt")).toBeInTheDocument();
  });

  it("shows an em dash rather than a blank where there is no holding time", async () => {
    renderQueue([testRequest({ due_at: null, due_at_basis: "" })]);

    const row = await rowFor("WE-202609-0042");

    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("marks a breached row as overdue", async () => {
    renderQueue([
      testRequest({ due_at: "2026-09-09T02:00:00Z", due_at_basis: "collection", is_overdue: true }),
    ]);

    const row = await rowFor("WE-202609-0042");

    expect(within(row).getByText(/overdue/)).toBeInTheDocument();
  });

  it("warns above the table when anything is past its holding time", async () => {
    renderQueue([
      testRequest({ id: 1, is_overdue: true, due_at: "2026-09-09T02:00:00Z" }),
      testRequest({ id: 2, sample_code: "WE-202609-0043", is_overdue: true, due_at: "2026-09-09T03:00:00Z" }),
      testRequest({ id: 3, sample_code: "WE-202609-0044" }),
    ]);

    expect(await screen.findByText(/2 analyses are past the holding time/)).toBeInTheDocument();
  });

  it("stays quiet when nothing is overdue", async () => {
    renderQueue([testRequest({ due_at: "2026-12-01T02:00:00Z", due_at_basis: "collection" })]);

    await rowFor("WE-202609-0042");

    expect(screen.queryByText(/past the holding time/)).not.toBeInTheDocument();
  });
});

describe("ordering", () => {
  it("renders rows in the order the server sent them", async () => {
    // The server orders by priority, then deadline (TestRequestViewSet.
    // _QUEUE_ORDER). This asserts the client does not re-sort: the rush row
    // is sent second here, and must stay second.
    renderQueue([
      testRequest({ id: 1, sample_code: "WE-202609-0001", sample_priority: "routine" }),
      testRequest({ id: 2, sample_code: "WE-202609-0002", sample_priority: "rush" }),
    ]);

    await rowFor("WE-202609-0001");
    const codes = screen
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getAllByRole("cell")[0].textContent);

    expect(codes).toEqual(["WE-202609-0001", "WE-202609-0002"]);
  });

  it("plays down routine priority and emphasises anything above it", async () => {
    renderQueue([
      testRequest({ id: 1, sample_code: "WE-202609-0001", sample_priority: "routine" }),
      testRequest({ id: 2, sample_code: "WE-202609-0002", sample_priority: "emergency" }),
    ]);

    const routine = await rowFor("WE-202609-0001");
    const emergency = await rowFor("WE-202609-0002");

    expect(within(routine).queryByText("Routine")?.tagName).toBe("SPAN");
    expect(within(emergency).getByText("Emergency").tagName).toBe("STRONG");
  });
});
