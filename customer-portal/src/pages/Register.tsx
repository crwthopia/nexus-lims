import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { registerCustomer } from "../api/auth";
import { describeApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

export function Register() {
  const { isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [prcLicenseNumber, setPrcLicenseNumber] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const register = useMutation({
    mutationFn: () =>
      registerCustomer({
        email,
        password,
        organization_name: organizationName || undefined,
        prc_license_number: prcLicenseNumber || undefined,
      }),
    onSuccess: () => setSubmitted(true),
  });

  if (isAuthenticated) return <Navigate to="/" replace />;

  if (submitted) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "70vh" }}>
        <div className="card" style={{ padding: 40, width: 420, textAlign: "center" }}>
          <h1 style={{ fontSize: "1.3rem", margin: "0 0 12px" }}>Check your email</h1>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
            We sent a verification link to <strong>{email}</strong>. Click it to activate your account, then log in.
          </p>
          <Link to="/login" className="btn btn-primary" style={{ marginTop: 16, display: "inline-flex" }}>
            Go to login
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "70vh" }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          register.mutate();
        }}
        className="card"
        style={{ padding: 40, width: 380, display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div>
          <h1 style={{ fontSize: "1.3rem", margin: "0 0 4px" }}>Create an account</h1>
          <p style={{ color: "var(--color-text-muted)", margin: 0, fontSize: "0.85rem" }}>NASAT Labs Customer Portal</p>
        </div>
        <label className="field">
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="field">
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        </label>
        <label className="field">
          Organization (optional)
          <input value={organizationName} onChange={(e) => setOrganizationName(e.target.value)} />
        </label>
        <label className="field">
          PRC license number (optional)
          <input value={prcLicenseNumber} onChange={(e) => setPrcLicenseNumber(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary" disabled={register.isPending}>
          Register
        </button>
        {register.isError && (
          <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", margin: 0 }}>{describeApiError(register.error)}</p>
        )}
        <p style={{ fontSize: "0.85rem", color: "var(--color-text-muted)", margin: 0 }}>
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  );
}
