/**
 * ProtectedRoute: the gate every non-login screen sits behind (App.tsx).
 *
 * The bug worth guarding is the three-state one. `isAuthenticated` is
 * `!!user`, and `user` is `undefined` while the staff-me query is still in
 * flight -- so a guard that only checks `isAuthenticated` bounces a
 * logged-in user to /login for the duration of the first request, on every
 * cold load. The `isLoading` branch is what prevents that, and nothing else
 * in the app would fail if it were removed.
 */

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProtectedRoute } from "./ProtectedRoute";
import { renderWithProviders, staffUser, stubApi } from "../test/helpers";

const SECRET = "Samples worklist";

function renderGuarded() {
  return renderWithProviders(
    <ProtectedRoute>
      <div>{SECRET}</div>
    </ProtectedRoute>,
    { route: "/samples", path: "/samples" },
  );
}

describe("ProtectedRoute", () => {
  it("renders the guarded screen for an authenticated user", async () => {
    stubApi({ "/auth/staff/me": { body: staffUser() } });

    renderGuarded();

    expect(await screen.findByText(SECRET)).toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("redirects to /login once the staff-me request comes back unauthenticated", async () => {
    stubApi({
      "/auth/staff/me": { status: 403, body: { detail: "Authentication credentials were not provided." } },
    });

    renderGuarded();

    expect(await screen.findByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("shows a loading state instead of redirecting while staff-me is in flight", async () => {
    // A fetch that never settles holds the query in its loading state for the
    // whole test, which is exactly the window the isLoading branch exists to
    // cover. Without that branch this renders "Login page" immediately --
    // a logged-in user flicker-redirected to login on every cold load.
    stubApi({ "/auth/staff/me": { body: staffUser() } });
    const pending = new Promise<Response>(() => {});
    globalThis.fetch = (() => pending) as unknown as typeof fetch;

    renderGuarded();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("does not leave the guarded screen mounted after the session goes away", async () => {
    stubApi({
      "/auth/staff/me": { status: 401, body: { detail: "Invalid session." } },
    });

    renderGuarded();

    // A 401 is the "your session expired" case; it must land on login, not
    // on a half-rendered screen whose own queries will each fail with 401.
    await waitFor(() => expect(screen.getByText("Login page")).toBeInTheDocument());
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });
});
