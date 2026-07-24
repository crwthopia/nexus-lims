import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { verifyEmail } from "../api/auth";
import { describeApiError } from "../api/client";

/**
 * The verification email's link (apps/accounts/customer_auth.py
 * send_verification_email) points at `{CUSTOMER_PORTAL_BASE_URL}/verify-email?token=...`,
 * so this page's whole job is reading that token and submitting it --
 * no user input needed, just an automatic POST on mount.
 */
export function VerifyEmail() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const verify = useMutation({
    mutationFn: (t: string) => verifyEmail(t),
  });

  useEffect(() => {
    if (token) verify.mutate(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "70vh" }}>
      <div className="card" style={{ padding: 40, width: 420, textAlign: "center" }}>
        {!token && (
          <>
            <h1 style={{ fontSize: "1.3rem", margin: "0 0 8px" }}>Missing verification link</h1>
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
              This page needs a verification token — use the link from your email.
            </p>
          </>
        )}
        {token && verify.isPending && <p style={{ color: "var(--color-text-muted)" }}>Verifying…</p>}
        {token && verify.isSuccess && (
          <>
            <h1 style={{ fontSize: "1.3rem", margin: "0 0 8px" }}>Email verified</h1>
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>Your account is now active.</p>
            <Link to="/login" className="btn btn-primary" style={{ marginTop: 16, display: "inline-flex" }}>
              Go to login
            </Link>
          </>
        )}
        {token && verify.isError && (
          <>
            <h1 style={{ fontSize: "1.3rem", margin: "0 0 8px", color: "var(--color-danger)" }}>Verification failed</h1>
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>{describeApiError(verify.error)}</p>
          </>
        )}
      </div>
    </div>
  );
}
