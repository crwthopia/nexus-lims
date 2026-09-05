import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useCreateTestResult,
  useInstruments,
  useInvestigationsForTestResult,
  useOpenInvestigation,
  useStandardReagents,
  useTestMethod,
  useTestRequest,
  useTestRequestAction,
  useTestResults,
} from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import {
  INVESTIGATION_STATUS_LABELS,
  INVESTIGATION_WRITE_ROLES,
  TEST_REQUEST_ACTIONS_BY_STATUS,
  TEST_REQUEST_ACTION_ROLES,
  TEST_REQUEST_STATUS_LABELS,
} from "../api/types";
import type { TestResult, TestResultDataType } from "../api/types";
import { PageHeader } from "../components/PageHeader";

const ACTION_LABELS: Record<string, string> = {
  start: "Start Testing",
  "submit-for-review": "Submit for Review",
  "flag-nonconforming": "Flag Nonconforming",
  "authorize-retest": "Authorize Retest",
  "resume-testing": "Resume Testing",
  complete: "Complete",
};

const DESTRUCTIVE_ACTIONS = new Set(["flag-nonconforming"]);

const DATA_TYPES: TestResultDataType[] = ["float", "int", "text", "date", "boolean", "list"];

export function TestRequestDetail() {
  const { id } = useParams<{ id: string }>();
  const testRequestId = Number(id);
  const { data: testRequest, isLoading, isError } = useTestRequest(testRequestId);
  const { data: testMethod } = useTestMethod(testRequest?.test_method);
  const { data: results } = useTestResults(testRequestId);
  const { data: instruments } = useInstruments();
  const { data: reagents } = useStandardReagents();
  const { hasRole, user } = useAuth();
  const canOpenInvestigation = hasRole(...INVESTIGATION_WRITE_ROLES);
  const requestAction = useTestRequestAction(testRequestId, testRequest?.sample);
  const createResult = useCreateTestResult(testRequestId);

  const [dataType, setDataType] = useState<TestResultDataType>("float");
  const [analyte, setAnalyte] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const [instrumentId, setInstrumentId] = useState("");
  const [reagentIds, setReagentIds] = useState<number[]>([]);

  if (isLoading) return <div>Loading…</div>;
  if (isError || !testRequest) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this test request.</div>;

  const availableActions = TEST_REQUEST_ACTIONS_BY_STATUS[testRequest.status] ?? [];
  const isCertified = user?.instrument_certifications.includes(testRequest.test_method) ?? false;
  const limits = testMethod?.specification_limits ?? {};
  const hasLimits = limits.min !== undefined || limits.max !== undefined;

  function toggleReagent(reagentId: number) {
    setReagentIds((prev) => (prev.includes(reagentId) ? prev.filter((r) => r !== reagentId) : [...prev, reagentId]));
  }

  function submitResult(e: React.FormEvent) {
    e.preventDefault();
    createResult.mutate(
      {
        analyte,
        data_type: dataType,
        value,
        unit,
        instrument: instrumentId ? Number(instrumentId) : null,
        standard_reagents: reagentIds,
      },
      {
        onSuccess: () => {
          // Cleared like the others: consecutive entries against one request
          // are usually *different* parameters, so keeping the last one would
          // mislabel the next result rather than save typing.
          setAnalyte("");
          setValue("");
          setUnit("");
          setInstrumentId("");
          setReagentIds([]);
        },
      },
    );
  }

  return (
    <div>
      <PageHeader
        back={{ to: `/samples/${testRequest.sample}`, label: testRequest.sample_code }}
        title={testRequest.test_method_name}
        meta={
          <span className="badge badge-neutral">
            {TEST_REQUEST_STATUS_LABELS[testRequest.status]}
          </span>
        }
      />

      <div className="detail-grid">
        <div className="stack">
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Test method</h2>
            <dl className="field-grid">
              <Field label="Method reference" value={testMethod?.method_reference || "—"} />
              <Field
                label="Specification limits"
                value={hasLimits ? `${limits.min ?? "–"} to ${limits.max ?? "–"}` : "Not numerically bounded"}
              />
            </dl>
            {!isCertified && (
              <p
                style={{
                  background: "var(--color-warning-bg)",
                  color: "var(--color-warning)",
                  borderRadius: "var(--radius)",
                  padding: "8px 10px",
                  fontSize: "0.8rem",
                  margin: "10px 0 0",
                }}
              >
                You're not certified for this test method (FR-C3-02) — entering a result will be rejected server-side.
              </p>
            )}
          </div>

          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Results</h2>
            {!results || results.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No results entered yet.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Parameter</th>
                    <th>Value</th>
                    <th>Entered by</th>
                    <th>Entered</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <ResultRow key={r.id} result={r} canOpenInvestigation={canOpenInvestigation} />
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {(testRequest.status === "assigned" || testRequest.status === "in_progress") && (
            <div className="card" style={{ padding: 20 }}>
              <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Enter a result</h2>
              <form onSubmit={submitResult} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", gap: 10 }}>
                  <label style={labelStyle}>
                    Data type
                    <select
                      value={dataType}
                      onChange={(e) => setDataType(e.target.value as TestResultDataType)}
                    >
                      {DATA_TYPES.map((dt) => (
                        <option key={dt} value={dt}>
                          {dt}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label style={labelStyle}>
                    Parameter
                    <input
                      value={analyte}
                      onChange={(e) => setAnalyte(e.target.value)}
                      placeholder="e.g. Lead — leave blank if the method reports one value"
                    />
                  </label>
                  <label style={labelStyle}>
                    Value
                    <input value={value} onChange={(e) => setValue(e.target.value)} required />
                  </label>
                  <label style={labelStyle}>
                    Unit
                    <input value={unit} onChange={(e) => setUnit(e.target.value)} />
                  </label>
                </div>

                <label style={labelStyle}>
                  Instrument (optional)
                  <select value={instrumentId} onChange={(e) => setInstrumentId(e.target.value)}>
                    <option value="">—</option>
                    {instruments?.results.map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.name}
                      </option>
                    ))}
                  </select>
                </label>

                {reagents && reagents.results.length > 0 && (
                  <div>
                    <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: 4 }}>
                      Standard reagents used (optional)
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                      {reagents.results.map((r) => (
                        <label key={r.id} style={{ fontSize: "0.85rem", display: "flex", alignItems: "center", gap: 4 }}>
                          <input
                            type="checkbox"
                            checked={reagentIds.includes(r.id)}
                            onChange={() => toggleReagent(r.id)}
                          />
                          {r.name} (lot {r.lot_number})
                        </label>
                      ))}
                    </div>
                  </div>
                )}

                <button type="submit" className="btn btn-primary" disabled={createResult.isPending} style={{ alignSelf: "start" }}>
                  Save result
                </button>
                {createResult.isError && (
                  <p style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>{describeApiError(createResult.error)}</p>
                )}
              </form>
            </div>
          )}
        </div>

        <div className="card" style={{ padding: 20, alignSelf: "start" }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Actions</h2>
          {availableActions.length === 0 && (
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No further actions from this status.</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {availableActions.map((name) => {
              const allowedRoles = TEST_REQUEST_ACTION_ROLES[name] ?? [];
              const permitted = hasRole(...allowedRoles);
              return (
                <button
                  key={name}
                  className={`btn ${DESTRUCTIVE_ACTIONS.has(name) ? "btn-danger" : "btn-primary"}`}
                  disabled={!permitted || requestAction.isPending}
                  title={permitted ? undefined : `Requires role: ${allowedRoles.join(" or ")}`}
                  onClick={() => requestAction.mutate(name)}
                >
                  {ACTION_LABELS[name] ?? name}
                </button>
              );
            })}
          </div>
          {requestAction.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>
              {describeApiError(requestAction.error)}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Its own component (rather than inline in the map()) because it needs the
 * per-result useInvestigationsForTestResult/useOpenInvestigation hooks --
 * calling those inside a .map() callback would violate the rules of hooks.
 */
function ResultRow({ result, canOpenInvestigation }: { result: TestResult; canOpenInvestigation: boolean }) {
  const navigate = useNavigate();
  const { data: investigations } = useInvestigationsForTestResult(result.id);
  const openInvestigation = useOpenInvestigation();
  const investigation = investigations?.results[0];

  return (
    <tr style={{ cursor: "default" }}>
      {/* Blank for single-parameter methods, where the method name already
          says what was measured. */}
      <td>{result.analyte || "—"}</td>
      <td>
        {result.value} {result.unit}
        {result.is_out_of_spec && (
          <span className="badge" style={{ background: "var(--color-danger-bg)", color: "var(--color-danger)", marginLeft: 8 }}>
            Out of spec
          </span>
        )}
      </td>
      <td>{result.entered_by_display_name || "—"}</td>
      <td>{new Date(result.entered_at).toLocaleString()}</td>
      <td>
        {result.is_out_of_spec &&
          (investigation ? (
            <Link to={`/investigations/${investigation.id}`} style={{ fontSize: "0.8rem" }}>
              {INVESTIGATION_STATUS_LABELS[investigation.status]}
            </Link>
          ) : (
            canOpenInvestigation && (
              <button
                className="btn"
                disabled={openInvestigation.isPending}
                onClick={() =>
                  openInvestigation.mutate(
                    { related_test_result: result.id, type: "oos" },
                    { onSuccess: (inv) => navigate(`/investigations/${inv.id}`) },
                  )
                }
              >
                Open Investigation
              </button>
            )
          ))}
      </td>
    </tr>
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

const labelStyle = { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", flex: 1 } as const;
