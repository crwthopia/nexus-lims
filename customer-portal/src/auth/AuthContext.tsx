import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, logoutCustomer } from "../api/auth";
import type { CustomerMe } from "../api/types";

interface AuthContextValue {
  user: CustomerMe | null | undefined;
  isLoading: boolean;
  isAuthenticated: boolean;
  refetchUser: () => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  // A 401/403 here just means "not logged in" -- React Query captures that
  // in query.error rather than throwing, and retry:false stops it from
  // retrying a request that will never succeed until the customer logs in.
  const { data: user, isLoading, refetch } = useQuery({
    queryKey: ["customer-me"],
    queryFn: getMe,
    retry: false,
  });

  async function logout() {
    await logoutCustomer();
    // setQueryData(key, undefined) is a documented no-op in TanStack Query
    // (it's the signal for "don't update"), so null is used instead --
    // same lesson learned building the Staff Console's AuthContext.
    queryClient.setQueryData(["customer-me"], null);
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "customer-me" });
  }

  const value: AuthContextValue = {
    user,
    isLoading,
    isAuthenticated: !!user,
    refetchUser: () => refetch(),
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() must be used within an AuthProvider");
  return ctx;
}
