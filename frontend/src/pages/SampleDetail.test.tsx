/**
 * SampleDetail's Actions panel: which FSM transitions are offered, and which
 * are disabled.
 *
 * Two independent gates decide each button, and both mirror a server-side
 * rule rather than inventing one:
 *
 *   1. SAMPLE_ACTIONS_BY_STATUS (api/types.ts) mirrors the Sample FSM edges
 *      in apps/samples/models.py. Offering an action the FSM doesn't allow
 *      from the current status produces a guaranteed 400.
 *   2. SAMPLE_ACTION_ROLES mirrors the per-action role gates on the API, and
 *      the water_environmental segregation-of-duties rule mirrors
 *      apps/review/services.check_can_approve.
 *
 * The server is the real guard in both cases, so a bug here is never a
 * security hole -- it's a button that fails on click, or a missing button
 * that blocks someone entitled to act. Both are invisible to the backend
 * suite, which is why these live here.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SampleDetail } from "./SampleDetail";
import { renderWithProviders, role, sampleDetail, sampleDetailRoutes, staffUser, stubApi } from "../test/helpers";
import type { SampleDetail as SampleDetailType, StaffMe } from "../api/types";

function renderSample(sample: SampleDetailType, user: StaffMe, extra = {}) {
  const routes = sampleDetailRoutes(sample, { "/auth/staff/me": { body: user }, ...extra });
  const stub = stubApi(routes);
  renderWithProviders(<SampleDetail />, { route: `/samples/${sample.id}`, path: "/samples/:id" });
  return stub;
}

async function actionsPanel() {
  // Scope queries to the Actions card so a "Reject" heading or history entry
  // elsewhere on the page can't satisfy a button assertion.
  const heading = await screen.findByRole("heading", { name: "Actions" });
  return heading.closest(".card") as HTMLElement;
}

describe("which actions are offered", () => {
  it("offers exactly the FSM edges legal from under_review", async () => {
    renderSample(sampleDetail({ status: "under_review" }), staffUser({ roles: [role("approver"), role("reviewer")] }));
    await actionsPanel();

    for (const label of ["Record Review", "Approve", "Reject"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    // Not reachable from under_review -- offering it would be a certain 400.
    expect(screen.queryByRole("button", { name: "Start Testing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dispose" })).not.toBeInTheDocument();
  });

  it("offers only Receive from registered", async () => {
    renderSample(sampleDetail({ status: "registered" }), staffUser({ roles: [role("sample_receiver")] }));
    await actionsPanel();

    expect(screen.getByRole("button", { name: "Receive" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("offers nothing from a terminal status", async () => {
    renderSample(sampleDetail({ status: "approved" }), staffUser({ roles: [role("approver")] }));
    await actionsPanel();

    expect(screen.getByText("No further actions from this status.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
});

describe("role gating", () => {
  it("disables an action the user lacks the role for, and says which role is needed", async () => {
    // An analyst has no business approving; the button is visible so the
    // workflow stays legible, but disabled with the reason in its tooltip.
    renderSample(sampleDetail({ status: "under_review" }), staffUser({ roles: [role("analyst")] }));
    await actionsPanel();

    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    expect(approve).toHaveAttribute("title", "Requires role: approver");
  });

  it("enables an action the user does hold the role for", async () => {
    renderSample(sampleDetail({ status: "under_review" }), staffUser({ roles: [role("approver")] }));
    await actionsPanel();

    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeEnabled();
    expect(approve).not.toHaveAttribute("title");
  });

  it("accepts any one of several permitted roles", async () => {
    // dispose allows qa_officer OR lab_supervisor -- holding either is enough.
    renderSample(
      sampleDetail({ status: "under_investigation" }),
      staffUser({ roles: [role("lab_supervisor")] }),
    );
    await actionsPanel();

    expect(screen.getByRole("button", { name: "Dispose" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Authorize Retest" })).toBeEnabled();
  });

  it("does not fire a request when a disabled action is clicked", async () => {
    const { calls } = renderSample(
      sampleDetail({ status: "under_review" }),
      staffUser({ roles: [role("analyst")] }),
    );
    await actionsPanel();

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(calls.some((c) => c.url.includes("/approve"))).toBe(false);
  });
});

describe("segregation of duties on a regulated service line", () => {
  const reviewedByMe = {
    "/review-actions/": {
      body: {
        count: 1,
        next: null,
        previous: null,
        results: [
          {
            id: 1,
            sample: 1,
            reviewer: 1,
            reviewer_display_name: "Test Staff",
            comments: "Looks fine",
            created_at: "2026-07-02T00:00:00Z",
          },
        ],
      },
    },
  };

  it("blocks approving a water_environmental sample the same person reviewed", async () => {
    renderSample(
      sampleDetail({ status: "under_review", service_line: "water_environmental" }),
      staffUser({ id: 1, roles: [role("approver"), role("reviewer")] }),
      reviewedByMe,
    );
    await actionsPanel();

    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    expect(approve.getAttribute("title")).toContain("must be a different");
    expect(screen.getByText(/you can't also approve it/)).toBeInTheDocument();

    // Reject is a different disposition and is not part of the split.
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("permits self-approval on failure_analysis, which is not regulated", async () => {
    // The Blueprint's documented bypass: the hard Reviewer != Approver split
    // applies to Water/Environmental only.
    renderSample(
      sampleDetail({ status: "under_review", service_line: "failure_analysis" }),
      staffUser({ id: 1, roles: [role("approver"), role("reviewer")] }),
      reviewedByMe,
    );
    await actionsPanel();

    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.queryByText(/you can't also approve it/)).not.toBeInTheDocument();
  });

  it("permits approving a water_environmental sample somebody else reviewed", async () => {
    renderSample(
      sampleDetail({ status: "under_review", service_line: "water_environmental" }),
      staffUser({ id: 2, roles: [role("approver")] }),
      reviewedByMe,
    );
    await actionsPanel();

    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.queryByText(/you can't also approve it/)).not.toBeInTheDocument();
  });
});

describe("running an action", () => {
  it("posts to the action's own endpoint", async () => {
    const { calls } = renderSample(
      sampleDetail({ id: 7, status: "registered" }),
      staffUser({ roles: [role("sample_receiver")] }),
      { "POST /samples/7/receive/": { body: sampleDetail({ id: 7, status: "received" }) } },
    );
    await actionsPanel();

    await userEvent.click(screen.getByRole("button", { name: "Receive" }));

    const post = calls.find((c) => c.method === "POST");
    expect(post?.url).toContain("/samples/7/receive/");
  });

  it("sends review comments in the body for the review action only", async () => {
    const { calls } = renderSample(
      sampleDetail({ id: 7, status: "under_review" }),
      staffUser({ roles: [role("reviewer")] }),
      { "POST /samples/7/review/": { body: sampleDetail({ id: 7, status: "under_review" }) } },
    );
    await actionsPanel();

    await userEvent.type(screen.getByPlaceholderText("Review comments (optional)"), "Spec met");
    await userEvent.click(screen.getByRole("button", { name: "Record Review" }));

    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ comments: "Spec met" });
  });

  it("surfaces a server rejection instead of failing silently", async () => {
    renderSample(
      sampleDetail({ id: 7, status: "under_review" }),
      staffUser({ roles: [role("approver")] }),
      {
        "POST /samples/7/approve/": {
          status: 400,
          body: { detail: "Approver must differ from the Reviewer for this service line." },
        },
      },
    );
    await actionsPanel();

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    // describeApiError unwraps {"detail": ...} -- the point is that the
    // server's own reason reaches the user, since the client-side mirror of
    // these rules is defence in depth and can legitimately be out of date.
    expect(
      await screen.findByText("Approver must differ from the Reviewer for this service line."),
    ).toBeInTheDocument();
  });
});
