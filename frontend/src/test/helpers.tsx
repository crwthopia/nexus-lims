/**
 * Test helpers for the Staff Console suite.
 *
 * The deliberate choice here is that `fetch` is the only thing stubbed --
 * not `AuthContext`, not the React Query hooks, not `api/client.ts`. Every
 * test therefore exercises the real client (CSRF header, ApiError mapping,
 * 204 handling), the real provider, and the real component. Mocking the
 * hooks instead would leave exactly the wiring these tests exist to protect
 * untested, and would keep passing after that wiring broke.
 */

import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import type { Role, RoleName, SampleDetail, StaffMe } from "../api/types";

/** One route in the stub API: a path suffix matched against the request URL. */
export interface StubRoute {
  /** HTTP status to return. Defaults to 200. */
  status?: number;
  /** JSON body. Omit entirely for a 204. */
  body?: unknown;
}

/**
 * Replaces global.fetch with a table keyed on "METHOD /path" (or just
 * "/path" to match any method). Longest matching key wins, so a specific
 * "/samples/1/approve/" entry beats a general "/samples/".
 *
 * An unmatched request fails the test loudly rather than returning a
 * plausible-looking empty result -- a silent {} is how a broken query key
 * survives a test suite.
 */
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

    calls.push({
      method,
      url,
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    });

    if (!key) {
      throw new Error(`stubApi: no route for ${method} ${url}. Known routes: ${Object.keys(routes).join(", ")}`);
    }

    const route = routes[key];
    const status = route.status ?? 200;
    const hasBody = "body" in route;

    return new Response(hasBody ? JSON.stringify(route.body) : null, {
      status: hasBody ? status : 204,
      headers: hasBody ? { "content-type": "application/json" } : {},
    });
  });

  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

/** Renders `ui` inside the providers the app supplies in main.tsx. */
export function renderWithProviders(
  ui: ReactNode,
  { route = "/", path }: { route?: string; path?: string } = {},
) {
  // retry:false so a stubbed 4xx settles immediately instead of being
  // retried past the test's own timeout; gcTime:0 so no cache survives into
  // the next test in the same file.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          {path ? (
            <Routes>
              <Route path={path} element={ui} />
              <Route path="/login" element={<div>Login page</div>} />
            </Routes>
          ) : (
            <Routes>
              <Route path="*" element={ui} />
              <Route path="/login" element={<div>Login page</div>} />
            </Routes>
          )}
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let nextRoleId = 1;

export function role(name: RoleName): Role {
  return { id: nextRoleId++, name } as Role;
}

export function staffUser(overrides: Partial<StaffMe> = {}): StaffMe {
  return {
    id: 1,
    display_name: "Test Staff",
    email: "staff@nasatlabs.test",
    roles: [],
    is_active: true,
    instrument_certifications: [],
    prc_license_number: null,
    prc_license_validity_date: null,
    ...overrides,
  };
}

export function sampleDetail(overrides: Partial<SampleDetail> = {}): SampleDetail {
  return {
    id: 1,
    order: null,
    service_line: "failure_analysis",
    unique_sample_code: "FA-2026-0001",
    client_reference: "",
    sampling_point: "",
    collection_datetime: null,
    container_type: "",
    container_count: 1,
    preservation_method: "",
    retention_period: "",
    holding_time: null,
    status: "under_review",
    safety_flags: [],
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    chain_of_custody_events: [],
    ...overrides,
  };
}

/** The three endpoints SampleDetail always fetches, so each test only declares what it varies. */
export function sampleDetailRoutes(sample: SampleDetail, extra: Record<string, StubRoute> = {}) {
  return {
    "/auth/staff/me": { body: staffUser() },
    [`/samples/${sample.id}/`]: { body: sample },
    "/review-actions/": { body: { count: 0, next: null, previous: null, results: [] } },
    "/approval-actions/": { body: { count: 0, next: null, previous: null, results: [] } },
    "/test-requests/": { body: { count: 0, next: null, previous: null, results: [] } },
    "/investigations/": { body: { count: 0, next: null, previous: null, results: [] } },
    ...extra,
  };
}
