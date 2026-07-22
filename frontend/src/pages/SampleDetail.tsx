import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useSample, useSampleAction } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { StatusBadge } from "../components/StatusBadge";
import { ApiError } from "../api/client";
import { SAMPLE_ACTIONS_BY_STATUS, SAMPLE_ACTION_ROLES } from "../api/types";

const ACTION_LABELS: Record<string, string> = {
  register: "Register",
  receive: "Receive",
  "start-prep": "Start Prep",
  "start-testing": "Start Testing",
  "submit-for-review": "Submit for Review",
  review: "Record Review",
  approve: "Approve",
  reject: "Reject",
  "authorize-retest": "Authorize Retest",
  dispose: "Dispose",
  "requeue-for-retest": "Requeue for Retest",
};

const DESTRUCTIVE_ACTIONS = new Set(["reject", "dispose"]);

export function SampleDetail() {
  const { id } = useParams<{ id: string }>();
  const sampleId = Number(id);
  const { data: sample, isLoading, isError } = useSample(sampleId);
  const { hasRole } = useAuth();
  const action = useSampleAction(sampleId);
  const [comments, setComments] = useState("");

  if (isLoading) return <div>Loading…</div>;
  if (isError || !sample) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this sample.</div>;

  const availableActions = SAMPLE_ACTIONS_BY_STATUS[sample.status] ?? [];

  function runAction(name: string) {
    const body = name === "review" ? { comments } : undefined;
    action.mutate(
      { action: name, body },
      {
        onSuccess: () => setComments(""),
      },
    );
  }

  return (
    <div>
      <Link to="/samples" style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
        ← Back to samples
      </Link>

      <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "12px 0 24px" }}>
        <h1 style={{ fontSize: "1.4rem", margin: 0 }}>{sample.unique_sample_code}</h1>
        <StatusBadge status={sample.status} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Details</h2>
          <dl style={fieldGridStyle}>
            <Field label="Service line" value={sample.service_line.replace("_", " ")} />
            <Field label="Client reference" value={sample.client_reference || "—"} />
            <Field label="Sampling point" value={sample.sampling_point || "—"} />
            <Field label="Container" value={`${sample.container_count}× ${sample.container_type || "unspecified"}`} />
            <Field label="Preservation method" value={sample.preservation_method || "—"} />
            <Field
              label="Collection date"
              value={sample.collection_datetime ? new Date(sample.collection_datetime).toLocaleString() : "—"}
            />
            <Field label="Created" value={new Date(sample.created_at).toLocaleString()} />
            <Field label="Last updated" value={new Date(sample.updated_at).toLocaleString()} />
          </dl>

          <h2 style={{ fontSize: "1rem", margin: "24px 0 12px" }}>Chain of custody</h2>
          {sample.chain_of_custody_events.length === 0 ? (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No custody events recorded yet.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.9rem" }}>
              {sample.chain_of_custody_events.map((event) => (
                <li
                  key={event.id}
                  style={{ padding: "8px 0", borderTop: "1px solid var(--color-border)" }}
                >
                  <strong style={{ textTransform: "capitalize" }}>{event.event_type}</strong>{" "}
                  <span style={{ color: "var(--color-text-muted)" }}>
                    {new Date(event.timestamp).toLocaleString()}
                    {event.to_location ? ` — ${event.to_location}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Actions</h2>

          {availableActions.length === 0 && (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
              No further actions from this status.
            </p>
          )}

          {availableActions.includes("review") && (
            <textarea
              placeholder="Review comments (optional)"
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              rows={3}
              style={{
                width: "100%",
                marginBottom: 10,
                padding: 8,
                borderRadius: "var(--radius)",
                border: "1px solid var(--color-border)",
                fontFamily: "inherit",
                fontSize: "0.85rem",
              }}
            />
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {availableActions.map((name) => {
              const allowedRoles = SAMPLE_ACTION_ROLES[name] ?? [];
              const permitted = hasRole(...allowedRoles);
              return (
                <button
                  key={name}
                  className={`btn ${DESTRUCTIVE_ACTIONS.has(name) ? "btn-danger" : "btn-primary"}`}
                  disabled={!permitted || action.isPending}
                  title={permitted ? undefined : `Requires role: ${allowedRoles.join(" or ")}`}
                  onClick={() => runAction(name)}
                >
                  {ACTION_LABELS[name] ?? name}
                </button>
              );
            })}
          </div>

          {action.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>
              {action.error instanceof ApiError ? describeError(action.error) : "Something went wrong."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function describeError(error: ApiError): string {
  if (typeof error.body === "string") return error.body;
  if (error.body && typeof error.body === "object") {
    const values = Object.values(error.body as Record<string, unknown>).flat();
    if (values.length) return values.join(" ");
  }
  return error.message;
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
