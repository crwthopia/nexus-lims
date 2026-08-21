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
import type { CustomerMe } from "../api/types";

export interface AuthContextValue {
  user: CustomerMe | null | undefined;
  isLoading: boolean;
  isAuthenticated: boolean;
  refetchUser: () => void;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() must be used within an AuthProvider");
  return ctx;
}
