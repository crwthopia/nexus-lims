/**
 * Customer Portal route guard.
 *
 * Same three-state hazard as the Staff Console's guard (see that file), but
 * the consequence differs: the screens behind this one are RLS-scoped to the
 * calling customer, so rendering them without a settled session means every
 * query fires unauthenticated and the customer sees a page of errors rather
 * than a login form.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProtectedRoute } from "./ProtectedRoute";
import { UNAUTHENTICATED, customerUser, renderWithProviders, stubApi } from "../test/helpers";

const SECRET = "My samples";

function renderGuarded() {
  return renderWithProviders(
    <ProtectedRoute>
      <div>{SECRET}</div>
    </ProtectedRoute>,
    { route: "/samples", path: "/samples" },
  );
}

describe("ProtectedRoute", () => {
  it("renders the guarded screen for a logged-in customer", async () => {
    stubApi({ "/auth/customer/me": { body: customerUser() } });

    renderGuarded();

    expect(await screen.findByText(SECRET)).toBeInTheDocument();
  });

  it("redirects to /login when there is no session", async () => {
    stubApi(UNAUTHENTICATED);

    renderGuarded();

    expect(await screen.findByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("holds on a loading state instead of redirecting mid-flight", async () => {
    stubApi(UNAUTHENTICATED);
    const pending = new Promise<Response>(() => {});
    globalThis.fetch = (() => pending) as unknown as typeof fetch;

    renderGuarded();

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });
});
