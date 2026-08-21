/**
 * AuthContext: role gating and logout.
 *
 * `hasRole` is the Staff Console's only client-side authorization primitive
 * -- every action button, and the Review Queue's segregation-of-duties
 * awareness, funnels through it. The server is the real guard (see
 * apps/accounts/permissions.py), so a bug here doesn't let anyone past the
 * API; it shows people buttons that will fail, or hides ones they're
 * entitled to, which is the class of bug nobody notices until a user
 * complains.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "./AuthContext";
import { useAuth } from "./context";
import { role, staffUser, stubApi } from "../test/helpers";

function renderAuth() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const rendered = renderHook(() => useAuth(), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    ),
  });
  return { ...rendered, queryClient };
}

describe("hasRole", () => {
  it("is false for every role while unauthenticated", async () => {
    stubApi({ "/auth/staff/me": { status: 403, body: { detail: "Authentication credentials were not provided." } } });

    const { result } = renderAuth();
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.hasRole("approver")).toBe(false);
    // No arguments must not accidentally mean "yes": [].some() is false, but
    // only because hasRole checks !!user first -- an unauthenticated user
    // with a truthy short-circuit would flip this.
    expect(result.current.hasRole()).toBe(false);
  });

  it("matches when the user holds any one of the roles asked about", async () => {
    stubApi({ "/auth/staff/me": { body: staffUser({ roles: [role("analyst")] }) } });

    const { result } = renderAuth();
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    expect(result.current.hasRole("analyst")).toBe(true);
    // Variadic OR, not AND -- this is what lets one button accept
    // "qa_officer or lab_supervisor" (SAMPLE_ACTION_ROLES in api/types.ts).
    expect(result.current.hasRole("qa_officer", "analyst")).toBe(true);
    expect(result.current.hasRole("approver")).toBe(false);
    expect(result.current.hasRole()).toBe(false);
  });

  it("does not treat an unrelated role as a match", async () => {
    stubApi({ "/auth/staff/me": { body: staffUser({ roles: [role("reviewer"), role("analyst")] }) } });

    const { result } = renderAuth();
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    expect(result.current.hasRole("approver")).toBe(false);
    expect(result.current.hasRole("system_administrator")).toBe(false);
  });
});

describe("logout", () => {
  it("clears the cached user to null, not undefined", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser({ roles: [role("analyst")] }) },
      "POST /auth/staff/logout": {},
    });

    const { result, queryClient } = renderAuth();
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    await act(async () => {
      await result.current.logout();
    });

    // The regression this guards, asserted on the cache rather than on the
    // hook: setQueryData(key, undefined) is a documented no-op in TanStack
    // Query, so clearing the cached user with `undefined` would leave the
    // *user object* sitting in the cache and isAuthenticated true until some
    // later background refetch happened to fail. null is a real cached
    // value. Note `toBeNull`, not a falsy check -- undefined would pass a
    // falsy assertion while being exactly the bug.
    expect(queryClient.getQueryData(["staff-me"])).toBeNull();
    await waitFor(() => expect(result.current.isAuthenticated).toBe(false));
    expect(result.current.user).toBeNull();
  });

  it("drops other cached queries but keeps the staff-me entry it just set", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser() },
      "POST /auth/staff/logout": {},
    });

    const { result, queryClient } = renderAuth();
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    // Stand in for the sample/test-request data a real session accumulates.
    queryClient.setQueryData(["samples", 1], { id: 1, unique_sample_code: "FA-2026-0001" });

    await act(async () => {
      await result.current.logout();
    });

    // One user's samples must not still be in memory for the next user, and
    // staff-me must survive as the deliberate null: a blanket clear() would
    // remove it outright and leave the next render depending on whatever an
    // async refetch reconciliation happens to do.
    expect(queryClient.getQueryData(["samples", 1])).toBeUndefined();
    expect(queryClient.getQueryState(["staff-me"])).not.toBeUndefined();
  });

  it("posts to the logout endpoint rather than only clearing local state", async () => {
    const { calls } = stubApi({
      "/auth/staff/me": { body: staffUser() },
      "POST /auth/staff/logout": {},
    });

    const { result } = renderAuth();
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    await act(async () => {
      await result.current.logout();
    });

    // A client-only logout would leave the Django session alive, so the next
    // visit would silently be logged back in.
    expect(calls.some((c) => c.method === "POST" && c.url.includes("/auth/staff/logout"))).toBe(true);
  });
});

describe("useAuth", () => {
  it("throws when used outside an AuthProvider", () => {
    // Rendering a bare consumer must fail loudly at the point of the mistake
    // rather than yielding undefined and crashing later on a property read.
    function Consumer() {
      useAuth();
      return null;
    }
    expect(() => render(<Consumer />)).toThrow(/must be used within an AuthProvider/);
  });
});

describe("logout button wiring", () => {
  it("calls logout from a click, not just from a direct hook call", async () => {
    const { calls } = stubApi({
      "/auth/staff/me": { body: staffUser() },
      "POST /auth/staff/logout": {},
    });

    function LogoutButton() {
      const { logout, isAuthenticated } = useAuth();
      return (
        <>
          <span>{isAuthenticated ? "signed in" : "signed out"}</span>
          <button onClick={() => void logout()}>Sign out</button>
        </>
      );
    }

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <LogoutButton />
        </AuthProvider>
      </QueryClientProvider>,
    );

    await screen.findByText("signed in");
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(screen.getByText("signed out")).toBeInTheDocument());
    expect(calls.some((c) => c.url.includes("/auth/staff/logout"))).toBe(true);
  });
});
