import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "../api/client";
import type { StaffMe } from "../api/types";

/**
 * Login is a real full-page navigation to Django (Entra ID SSO), not
 * something this SPA can do via fetch(). ?next= routes django-auth-adfs's
 * OAuth2CallbackView to StaffLoginCompleteView (backend/apps/accounts/urls.py,
 * config/urls.py), which bounces the browser back here once SSO completes --
 * see config/settings.py STAFF_CONSOLE_BASE_URL for why that indirection
 * exists (the callback can't cross dev-server ports on its own).
 */
export const LOGIN_URL = "http://localhost:8000/oauth2/login?next=/staff/login-complete/";

interface AuthContextValue {
  user: StaffMe | null | undefined;
  isLoading: boolean;
  isAuthenticated: boolean;
  hasRole: (...roleNames: string[]) => boolean;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  // A 401/403 here just means "not logged in" -- React Query captures that
  // in query.error rather than throwing, and retry:false stops it from
  // retrying a request that will never succeed until the user logs in.
  const { data: user, isLoading } = useQuery({
    queryKey: ["staff-me"],
    queryFn: () => apiGet<StaffMe>("/auth/staff/me"),
    retry: false,
  });

  async function logout() {
    await apiPost("/auth/staff/logout");
    // setQueryData(key, undefined) is a documented no-op in TanStack Query
    // (it's the signal for "don't update"), so it can't be used to clear
    // the cached user -- null is a real value and updates synchronously,
    // which is what makes isAuthenticated flip to false on this same
    // render instead of lagging behind an eventual background refetch.
    queryClient.setQueryData(["staff-me"], null);
    // Drop every other cached query (samples, etc.) except staff-me, which
    // we just set deterministically above -- letting clear() touch it too
    // would remove it outright and leave the next render relying on
    // whatever an async refetch/observer reconciliation happens to do.
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "staff-me" });
  }

  const value: AuthContextValue = {
    user,
    isLoading,
    isAuthenticated: !!user,
    hasRole: (...roleNames) => !!user && user.roles.some((r) => roleNames.includes(r.name)),
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() must be used within an AuthProvider");
  return ctx;
}
