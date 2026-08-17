/**
 * Test helpers for the Customer Portal suite.
 *
 * Same approach as the Staff Console's `src/test/helpers.tsx`: `fetch` is the
 * only stub, so every test exercises the real api/client.ts, api/auth.ts, and
 * AuthProvider. Kept as a separate copy rather than shared, because the two
 * frontends are deliberately separate apps with no shared code -- that
 * separation is the whole point of the two-identity-domain design, and a
 * shared test package would be the first crack in it.
 */

import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import type { CustomerMe } from "../api/types";

export interface StubRoute {
  status?: number;
  body?: unknown;
}

/** See the Staff Console helper for the matching rules; identical behaviour. */
export function stubApi(routes: Record<string, StubRoute>) {
  const calls: { method: string; url: string; body: unknown }[] = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = (init.method ?? "GET").toUpperCase();

    const key = Object.keys(routes)
      .filter((k) => {
        const [maybeMethod, ...rest] = k.split(" ");
        if (rest.length) return maybeMethod.toUpperCase() === method && url.includes(rest.join(" "));
        return url.includes(k);
      })
      .sort((a, b) => b.length - a.length)[0];

    calls.push({ method, url, body: init.body ? JSON.parse(String(init.body)) : undefined });

    if (!key) {
      throw new Error(`stubApi: no route for ${method} ${url}. Known routes: ${Object.keys(routes).join(", ")}`);
    }

    const route = routes[key];
    const hasBody = "body" in route;
    return new Response(hasBody ? JSON.stringify(route.body) : null, {
      status: hasBody ? (route.status ?? 200) : 204,
      headers: hasBody ? { "content-type": "application/json" } : {},
    });
  });

  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

/**
 * `path` is the route pattern `ui` is mounted at, and must be given whenever
 * it collides with one of the navigation placeholders below -- mounting the
 * Login page without `path: "/login"` would let the placeholder win the match
 * and silently render "Login page" instead of the component under test.
 */
export function renderWithProviders(
  ui: ReactNode,
  { route = "/", path }: { route?: string; path?: string } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });

  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          <Routes>
            <Route path={path ?? "*"} element={ui} />
            {/* Stand-ins so a <Navigate> is observable as rendered text. */}
            {path !== "/login" && <Route path="/login" element={<div>Login page</div>} />}
            {path !== "/" && <Route path="/" element={<div>Home page</div>} />}
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...rendered, queryClient };
}

export function customerUser(overrides: Partial<CustomerMe> = {}): CustomerMe {
  return {
    id: 1,
    email: "client@example.test",
    is_email_verified: true,
    mfa_enabled: false,
    organization_name: "Example Manufacturing",
    prc_license_number: null,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

/** Not logged in: what GET /auth/customer/me returns before a session exists. */
export const UNAUTHENTICATED = {
  "/auth/customer/me": { status: 403, body: { detail: "Authentication credentials were not provided." } },
};
