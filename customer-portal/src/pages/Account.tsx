import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { confirmMfa, enableMfa } from "../api/auth";
import { describeApiError } from "../api/client";
import { useAuth } from "../auth/context";

export function Account() {
  const { user, refetchUser } = useAuth();
  const [provisioning, setProvisioning] = useState<{ secret: string; provisioning_uri: string } | null>(null);
  const [code, setCode] = useState("");

  const enable = useMutation({
    mutationFn: enableMfa,
    onSuccess: (data) => setProvisioning(data),
  });

  const confirm = useMutation({
    mutationFn: () => confirmMfa(code),
    onSuccess: () => {
      setProvisioning(null);
      setCode("");
      refetchUser();
    },
  });

  if (!user) return null;

  return (
    <div style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: "1.4rem", margin: "0 0 20px" }}>Account</h1>

      <div className="card" style={{ padding: 20, marginBottom: 20 }}>
        <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Profile</h2>
        <dl style={{ display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 16, margin: 0 }}>
          <dt style={fieldLabel}>Email</dt>
          <dd style={fieldValue}>{user.email}</dd>
          <dt style={fieldLabel}>Email verified</dt>
          <dd style={fieldValue}>{user.is_email_verified ? "Yes" : "No"}</dd>
          <dt style={fieldLabel}>Organization</dt>
          <dd style={fieldValue}>{user.organization_name || "—"}</dd>
          <dt style={fieldLabel}>PRC license number</dt>
          <dd style={fieldValue}>{user.prc_license_number || "—"}</dd>
          <dt style={fieldLabel}>Member since</dt>
          <dd style={fieldValue}>{new Date(user.created_at).toLocaleDateString()}</dd>
        </dl>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Two-factor authentication</h2>
        {user.mfa_enabled ? (
          <p style={{ color: "var(--color-success)", fontSize: "0.9rem" }}>MFA is enabled on your account.</p>
        ) : provisioning ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <p style={{ fontSize: "0.85rem" }}>
              Add this secret to your authenticator app (Google Authenticator, Authy, etc.), then enter the 6-digit code
              it generates:
            </p>
            <code style={{ background: "var(--color-bg)", padding: "8px 10px", borderRadius: "var(--radius)", fontSize: "0.8rem", wordBreak: "break-all" }}>
              {provisioning.secret}
            </code>
            <label className="field">
              Authenticator code
              <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="6-digit code" autoFocus />
            </label>
            <button className="btn btn-primary" disabled={confirm.isPending} onClick={() => confirm.mutate()} style={{ alignSelf: "start" }}>
              Confirm
            </button>
            {confirm.isError && (
              <p style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>{describeApiError(confirm.error)}</p>
            )}
          </div>
        ) : (
          <>
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", marginBottom: 10 }}>
              Add an extra layer of security to your account with an authenticator app.
            </p>
            <button className="btn btn-primary" disabled={enable.isPending} onClick={() => enable.mutate()}>
              Enable MFA
            </button>
            {enable.isError && (
              <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 8 }}>{describeApiError(enable.error)}</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const fieldLabel = { color: "var(--color-text-muted)", fontSize: "0.8rem" } as const;
const fieldValue = { margin: "0 0 10px" } as const;
