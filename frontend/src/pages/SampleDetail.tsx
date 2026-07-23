import { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
  useInvestigationsForSample,
  useOpenInvestigation,
  useSample,
  useSampleAction,
  useSampleReviewHistory,
  useTestRequestsForSample,
} from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { StatusBadge } from "../components/StatusBadge";
import { describeApiError } from "../api/client";
import {
  INVESTIGATION_STATUS_LABELS,
  INVESTIGATION_WRITE_ROLES,
  SAMPLE_ACTIONS_BY_STATUS,
  SAMPLE_ACTION_ROLES,
  TEST_REQUEST_STATUS_LABELS,
} from "../api/types";

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

const SEGREGATION_OF_DUTIES_MESSAGE =
  "Water/Environmental Testing is a regulated service line: the Approver must be a different " +
  "person from the Reviewer who reviewed this sample (ASTM E1578-18 6.6.1).";

export function SampleDetail() {
  const { id } = useParams<{ id: string }>();
  const sampleId = Number(id);
  const { data: sample, isLoading, isError } = useSample(sampleId);
  const { reviewActions, approvalActions } = useSampleReviewHistory(sampleId);
  const { data: testRequests } = useTestRequestsForSample(sampleId);
  const { data: investigations } = useInvestigationsForSample(sampleId);
  const openInvestigation = useOpenInvestigation();
  const { user, hasRole } = useAuth();
  const action = useSampleAction(sampleId);
  const navigate = useNavigate();
  const [comments, setComments] = useState("");

  if (isLoading) return <div>Loading…</div>;
  if (isError || !sample) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this sample.</div>;

  const availableActions = SAMPLE_ACTIONS_BY_STATUS[sample.status] ?? [];

  // Mirrors apps/review/services.check_can_approve server-side: for the
  // regulated water_environmental line, an Approver may not approve a
  // sample they themselves reviewed. The server is the real guard (this is
  // defense in depth, same principle as CustomerOrderViewSet's RLS
  // reasoning) -- this just saves a doomed round trip and explains why,
  // rather than letting the click fail with a generic 400.
  const reviewedByMe = reviewActions.some((r) => r.reviewer === user?.id);
  const approveBlockedBySegregationOfDuties = sample.service_line === "water_environmental" && reviewedByMe;

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
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
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
                  <li key={event.id} style={{ padding: "8px 0", borderTop: "1px solid var(--color-border)" }}>
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
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Test requests</h2>
            {!testRequests || testRequests.results.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No test requests yet.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Test method</th>
                    <th>Status</th>
                    <th>Assigned analyst</th>
                  </tr>
                </thead>
                <tbody>
                  {testRequests.results.map((tr) => (
                    <tr key={tr.id} onClick={() => navigate(`/test-requests/${tr.id}`)}>
                      <td style={{ fontWeight: 600 }}>{tr.test_method_name}</td>
                      <td>{TEST_REQUEST_STATUS_LABELS[tr.status]}</td>
                      <td>{tr.assigned_analyst_display_name || "Unassigned"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {sample.status === "under_investigation" && (
            <div className="card" style={{ padding: 20 }}>
              <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Investigation</h2>
              {investigations && investigations.results.length > 0 ? (
                <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.9rem" }}>
                  {investigations.results.map((inv) => (
                    <li key={inv.id} style={{ padding: "6px 0", borderTop: "1px solid var(--color-border)" }}>
                      <Link to={`/investigations/${inv.id}`}>Investigation #{inv.id}</Link>{" "}
                      <span style={{ color: "var(--color-text-muted)" }}>
                        — {INVESTIGATION_STATUS_LABELS[inv.status]}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <>
                  <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
                    No investigation opened yet for this rejection (ISO/IEC 17025:2017 7.10).
                  </p>
                  {hasRole(...INVESTIGATION_WRITE_ROLES) && (
                    <button
                      className="btn btn-primary"
                      disabled={openInvestigation.isPending}
                      onClick={() =>
                        openInvestigation.mutate(
                          { related_sample: sampleId, type: "oos" },
                          { onSuccess: (inv) => navigate(`/investigations/${inv.id}`) },
                        )
                      }
                    >
                      Open Investigation
                    </button>
                  )}
                  {openInvestigation.isError && (
                    <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 10 }}>
                      {describeApiError(openInvestigation.error)}
                    </p>
                  )}
                </>
              )}
            </div>
          )}

          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Review &amp; approval history</h2>
            {reviewActions.length === 0 && approvalActions.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
                No review or approval recorded yet.
              </p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.9rem" }}>
                {reviewActions.map((r) => (
                  <li key={`review-${r.id}`} style={{ padding: "10px 0", borderTop: "1px solid var(--color-border)" }}>
                    <div>
                      <strong>Reviewed</strong> by {r.reviewer_display_name}
                      {r.reviewer === user?.id && (
                        <span style={{ color: "var(--color-text-muted)" }}> (you)</span>
                      )}
                    </div>
                    {r.comments && <div style={{ color: "var(--color-text-muted)", margin: "2px 0" }}>“{r.comments}”</div>}
                    <div style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>
                      {new Date(r.created_at).toLocaleString()}
                    </div>
                  </li>
                ))}
                {approvalActions.map((a) => (
                  <li key={`approval-${a.id}`} style={{ padding: "10px 0", borderTop: "1px solid var(--color-border)" }}>
                    <div>
                      <strong style={{ textTransform: "capitalize" }}>{a.disposition}</strong> by{" "}
                      {a.approver_display_name}
                      {a.approver === user?.id && <span style={{ color: "var(--color-text-muted)" }}> (you)</span>}
                    </div>
                    <div style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>
                      {new Date(a.created_at).toLocaleString()}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="card" style={{ padding: 20, alignSelf: "start" }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Actions</h2>

          {availableActions.length === 0 && (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
              No further actions from this status.
            </p>
          )}

          {approveBlockedBySegregationOfDuties && availableActions.includes("approve") && (
            <p
              style={{
                background: "var(--color-warning-bg)",
                color: "var(--color-warning)",
                borderRadius: "var(--radius)",
                padding: "8px 10px",
                fontSize: "0.8rem",
                margin: "0 0 10px",
              }}
            >
              You reviewed this sample yourself — you can't also approve it.
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
              const sodBlocked = name === "approve" && approveBlockedBySegregationOfDuties;
              const disabled = !permitted || sodBlocked || action.isPending;

              let title: string | undefined;
              if (!permitted) title = `Requires role: ${allowedRoles.join(" or ")}`;
              else if (sodBlocked) title = SEGREGATION_OF_DUTIES_MESSAGE;

              return (
                <button
                  key={name}
                  className={`btn ${DESTRUCTIVE_ACTIONS.has(name) ? "btn-danger" : "btn-primary"}`}
                  disabled={disabled}
                  title={title}
                  onClick={() => runAction(name)}
                >
                  {ACTION_LABELS[name] ?? name}
                </button>
              );
            })}
          </div>

          {action.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>
              {describeApiError(action.error)}
            </p>
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
