/**
 * Auth context, the hook that reads it, and the types they share.
 *
 * Separate from AuthContext.tsx, which holds only the provider component.
 * A module that exports both a component and a non-component breaks React
 * Fast Refresh -- editing the hook would remount the whole tree instead of
 * hot-swapping. Splitting them fixes it by construction rather than by
 * suppressing the lint rule.
 */

import { createContext, useContext } from "react";
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

export interface AuthContextValue {
  user: StaffMe | null | undefined;
  isLoading: boolean;
  isAuthenticated: boolean;
  hasRole: (...roleNames: string[]) => boolean;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() must be used within an AuthProvider");
  return ctx;
}
