/**
 * Training session detail: the session FSM actions and per-enrollment
 * controls.
 *
 * Same shape as SampleDetail's Actions panel and the same reasoning — two
 * client-side maps mirror server-side rules, so drift here shows people
 * buttons that cannot work rather than letting anyone past the API. The
 * difference is the gate: TrainingSession actions are gated purely by role
 * (TRAINING_WRITE_ROLES), so unlike a Sample action the button is *shown*
 * and disabled with the required role in its tooltip.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TrainingSessionDetail } from "./TrainingSessionDetail";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function session(overrides = {}) {
  return {
    id: 3,
    course: 1,
    course_title: "ISO 17025 Awareness",
    start_date: "2026-09-01",
    end_date: "2026-09-02",
    capacity: 20,
    min_capacity: 5,
    cancellation_threshold_days: 7,
    status: "scheduled",
    confirmed_enrollment_count: 4,
    ...overrides,
  };
}

function enrollment(overrides = {}) {
  return {
    id: 11,
    session: 3,
    customer: 7,
    customer_email: "client@example.test",
    payment_status: "paid",
    discount_applied: "0.00",
    discount_override: null,
    certificate_issued: false,
    status: "confirmed",
    created_at: "2026-08-01T09:00:00Z",
    ...overrides,
  };
}

function listOf(...results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

function render(
  user = staffUser({ roles: [role("training_coordinator")] }),
  sess = session(),
  enrollments = [enrollment()],
  extra = {},
) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/training-sessions/3/": { body: sess },
    "/enrollments/": { body: listOf(...enrollments) },
    ...extra,
  });
  renderWithProviders(<TrainingSessionDetail />, {
    route: "/training-sessions/3",
    path: "/training-sessions/:id",
  });
  return stub;
}

async function actionsPanel() {
  const heading = await screen.findByRole("heading", { name: "Actions" });
  return heading.closest(".card") as HTMLElement;
}

describe("which session actions are offered", () => {
  it("offers the FSM edges legal from scheduled", async () => {
    render();
    const panel = await actionsPanel();

    expect(within(panel).getByRole("button", { name: "Start Session" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Cancel Session" })).toBeInTheDocument();
    // Not reachable from scheduled — offering it would be a certain 400.
    expect(within(panel).queryByRole("button", { name: "Complete Session" })).not.toBeInTheDocument();
  });

  it("offers only completion once in progress", async () => {
    render(undefined, session({ status: "in_progress" }));
    const panel = await actionsPanel();

    expect(within(panel).getByRole("button", { name: "Complete Session" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Start Session" })).not.toBeInTheDocument();
  });

  it("offers only cancellation while pending reschedule", async () => {
    // check_session_capacity puts a session here when it is under-subscribed;
    // it cannot be started from this state.
    render(undefined, session({ status: "pending_reschedule" }));
    const panel = await actionsPanel();

    expect(within(panel).getByRole("button", { name: "Cancel Session" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Start Session" })).not.toBeInTheDocument();
  });

  it("offers nothing from a terminal status", async () => {
    render(undefined, session({ status: "completed" }));
    const panel = await actionsPanel();

    expect(within(panel).getByText("No further actions from this status.")).toBeInTheDocument();
  });
});

describe("the role gate on session actions", () => {
  it("disables them for a user without a training write role, naming the role needed", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    const panel = await actionsPanel();

    const start = within(panel).getByRole("button", { name: "Start Session" });
    expect(start).toBeDisabled();
    expect(start.getAttribute("title")).toContain("Requires role:");
  });

  it("enables them for a training coordinator", async () => {
    render();
    const panel = await actionsPanel();

    const start = within(panel).getByRole("button", { name: "Start Session" });
    expect(start).toBeEnabled();
    expect(start).not.toHaveAttribute("title");
  });

  it("fires no request when a disabled action is clicked", async () => {
    const { calls } = render(staffUser({ roles: [role("analyst")] }));
    const panel = await actionsPanel();

    await userEvent.click(within(panel).getByRole("button", { name: "Start Session" }));

    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("running a session action", () => {
  it("posts to the action's own endpoint", async () => {
    const { calls } = render(undefined, undefined, undefined, {
      "POST /training-sessions/3/start-session/": { body: session({ status: "in_progress" }) },
    });
    const panel = await actionsPanel();

    await userEvent.click(within(panel).getByRole("button", { name: "Start Session" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.url).toContain("/training-sessions/3/start-session/");
  });

  it("surfaces a server rejection", async () => {
    render(undefined, undefined, undefined, {
      "POST /training-sessions/3/start-session/": {
        status: 400,
        body: { detail: "Cannot start a session before its start date." },
      },
    });
    const panel = await actionsPanel();

    await userEvent.click(within(panel).getByRole("button", { name: "Start Session" }));

    expect(
      await screen.findByText("Cannot start a session before its start date."),
    ).toBeInTheDocument();
  });
});

describe("per-enrollment controls", () => {
  it("offers complete and cancel for a confirmed enrollment", async () => {
    render();
    await screen.findByText("client@example.test");

    expect(screen.getByRole("button", { name: "Complete" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("offers neither once the enrollment has left confirmed", async () => {
    // A cancelled enrollment has nothing further to complete, and the
    // server's own FSM would refuse either transition.
    render(undefined, undefined, [enrollment({ status: "cancelled" })]);
    await screen.findByText("client@example.test");

    expect(screen.queryByRole("button", { name: "Complete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("hides the whole control column from a user who cannot write", async () => {
    render(staffUser({ roles: [role("analyst")] }));
    await screen.findByText("client@example.test");

    expect(screen.queryByRole("button", { name: "Complete" })).not.toBeInTheDocument();
  });

  it("posts the action against the enrollment, not the session", async () => {
    const { calls } = render(undefined, undefined, undefined, {
      "POST /enrollments/11/complete/": { body: enrollment({ status: "completed" }) },
    });
    await screen.findByText("client@example.test");

    await userEvent.click(screen.getByRole("button", { name: "Complete" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.url).toContain("/enrollments/11/complete/");
  });
});
