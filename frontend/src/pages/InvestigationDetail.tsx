import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useCloseInvestigation, useInvestigation, useUpdateInvestigation } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { INVESTIGATION_STATUS_LABELS, INVESTIGATION_TYPE_LABELS, INVESTIGATION_WRITE_ROLES } from "../api/types";

export function InvestigationDetail() {
  const { id } = useParams<{ id: string }>();
  const investigationId = Number(id);
  const { data: investigation, isLoading, isError } = useInvestigation(investigationId);
  const { hasRole } = useAuth();
  const canWrite = hasRole(...INVESTIGATION_WRITE_ROLES);
  const update = useUpdateInvestigation(investigationId);
  const close = useCloseInvestigation(investigationId);

  const [rootCause, setRootCause] = useState("");
  const [capaActions, setCapaActions] = useState("");

  useEffect(() => {
    if (investigation) {
      setRootCause(investigation.root_cause);
      setCapaActions(investigation.capa_actions);
    }
  }, [investigation]);

  if (isLoading) return <div>Loading…</div>;
  if (isError || !investigation) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this investigation.</div>;

  const isClosed = investigation.status === "closed";

  function saveFindings(e: React.FormEvent) {
    e.preventDefault();
    update.mutate({ root_cause: rootCause, capa_actions: capaActions });
  }

  return (
    <div>
      <Link to="/investigations" style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
        ← Back to investigations
      </Link>

      <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "12px 0 24px" }}>
        <h1 style={{ fontSize: "1.4rem", margin: 0 }}>
          Investigation #{investigation.id}
          {investigation.related_sample_code && ` — ${investigation.related_sample_code}`}
        </h1>
        <span className="badge" style={{ background: "var(--color-bg)", color: "var(--color-text-muted)" }}>
          {INVESTIGATION_STATUS_LABELS[investigation.status]}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Details</h2>
            <dl style={fieldGridStyle}>
              <Field label="Type" value={INVESTIGATION_TYPE_LABELS[investigation.type]} />
              <Field
                label="Related to"
                value={
                  investigation.related_sample_code
                    ? investigation.related_sample_code
                    : investigation.related_test_result
                      ? `Test Result #${investigation.related_test_result}`
                      : "—"
                }
              />
              <Field label="Opened by" value={investigation.opened_by_display_name} />
              <Field label="Opened" value={new Date(investigation.opened_at).toLocaleString()} />
              <Field label="Closed" value={investigation.closed_at ? new Date(investigation.closed_at).toLocaleString() : "—"} />
            </dl>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Root cause &amp; CAPA</h2>
            {canWrite && !isClosed ? (
              <form onSubmit={saveFindings} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <label style={labelStyle}>
                  Root cause
                  <textarea rows={4} value={rootCause} onChange={(e) => setRootCause(e.target.value)} style={textareaStyle} />
                </label>
                <label style={labelStyle}>
                  Corrective and preventive actions
                  <textarea rows={4} value={capaActions} onChange={(e) => setCapaActions(e.target.value)} style={textareaStyle} />
                </label>
                <button type="submit" className="btn btn-primary" disabled={update.isPending} style={{ alignSelf: "start" }}>
                  Save
                </button>
                {update.isError && (
                  <p style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>{describeApiError(update.error)}</p>
                )}
              </form>
            ) : (
              <>
                <p style={{ fontSize: "0.9rem", whiteSpace: "pre-wrap" }}>
                  <strong>Root cause: </strong>
                  {investigation.root_cause || "—"}
                </p>
                <p style={{ fontSize: "0.9rem", whiteSpace: "pre-wrap" }}>
                  <strong>CAPA: </strong>
                  {investigation.capa_actions || "—"}
                </p>
              </>
            )}
          </div>
        </div>

        <div className="card" style={{ padding: 20, alignSelf: "start" }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Actions</h2>
          {isClosed ? (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>This investigation is closed.</p>
          ) : canWrite ? (
            <button className="btn btn-primary" disabled={close.isPending} onClick={() => close.mutate()}>
              Close investigation
            </button>
          ) : (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
              Requires role: {INVESTIGATION_WRITE_ROLES.join(" or ")}
            </p>
          )}
          {close.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>{describeApiError(close.error)}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>{label}</dt>
      <dd style={{ margin: "0 0 10px" }}>{value}</dd>
    </>
  );
}

const fieldGridStyle = { display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 16, margin: 0 } as const;
const labelStyle = { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" } as const;
const textareaStyle = {
  padding: 8,
  borderRadius: "var(--radius)",
  border: "1px solid var(--color-border)",
  fontFamily: "inherit",
  fontSize: "0.85rem",
} as const;
