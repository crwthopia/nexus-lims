import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { loginCustomer, type CustomerAuthErrorBody } from "../api/auth";
import { useAuth } from "../auth/context";

export function Login() {
  const { isAuthenticated, refetchUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [mfaRequired, setMfaRequired] = useState(false);

  const login = useMutation({
    mutationFn: () => loginCustomer({ email, password, mfa_code: mfaCode || undefined }),
    onSuccess: () => refetchUser(),
    onError: (error) => {
      if (error instanceof ApiError && (error.body as CustomerAuthErrorBody)?.code === "MFARequiredError") {
        setMfaRequired(true);
      }
    },
  });

  if (isAuthenticated) return <Navigate to="/" replace />;

  const errorBody = login.error instanceof ApiError ? (login.error.body as CustomerAuthErrorBody) : null;
  const errorMessage = errorBody?.detail ?? (login.isError ? "Something went wrong." : null);

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "70vh" }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
        className="card"
        style={{ padding: 40, width: 360, display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div>
          <h1 style={{ fontSize: "1.3rem", margin: "0 0 4px" }}>Log in</h1>
          <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.85rem" }}>NASAT Labs Customer Portal</p>
        </div>
        <label className="field">
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field">
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {mfaRequired && (
          <label className="field">
            Authenticator code
            <input value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} placeholder="6-digit code" autoFocus />
          </label>
        )}
        <button type="submit" className="btn btn-primary" disabled={login.isPending}>
          Log in
        </button>
        {errorMessage && <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", margin: 0 }}>{errorMessage}</p>}
        <p style={{ fontSize: "0.85rem", color: "var(--color-text-muted)", margin: 0 }}>
          Don't have an account? <Link to="/register">Register</Link>
        </p>
      </form>
    </div>
  );
}
