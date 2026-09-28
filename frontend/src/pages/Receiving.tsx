import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useSample, useSampleAction, useSampleByCode } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { PrintButton } from "../components/PrintButton";
import { StatusBadge } from "../components/StatusBadge";
import {
  RECEIPT_CHECKS,
  RECEIPT_CONDITION_LABELS,
  SAMPLE_PRIORITY_LABELS,
} from "../api/types";
import type { ReceiptCheckField, ReceiptCondition, ReceivePayload, Sample } from "../api/types";

/**
 * The receiving bench: scan a container, say what arrived in, print its
 * labels.
 *
 * It exists because the three things a receiving clerk does were three
 * screens and an API call. ISO/IEC 17025:2017 7.4.3 wants the condition of
 * an item recorded *as it is received*, which in practice means while the
 * cooler is still open — a checklist filled in afterwards from memory is
 * the thing the clause is written against. So the form is on the same
 * screen as the scan, and the labels come off the same action.
 *
 * Scanner-shaped, not mouse-shaped. A handheld scanner is a keyboard that
 * types a code and presses Enter, so the code field is autofocused, submits
 * on Enter, and refocuses itself after every sample so a clerk can work
 * through a delivery without touching the mouse.
 */
export function Receiving() {
  const { hasRole } = useAuth();
  const [code, setCode] = useState("");
  const [submitted, setSubmitted] = useState("");
  const codeInput = useRef<HTMLInputElement>(null);

  const { data: sample, isFetching, isError } = useSampleByCode(submitted);

  const mayReceive = hasRole("sample_receiver", "lab_supervisor", "system_administrator");

  useEffect(() => {
    codeInput.current?.focus();
  }, []);

  function lookUp(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(code.trim());
  }

  function startOver() {
    setCode("");
    setSubmitted("");
    codeInput.current?.focus();
  }

  return (
    <div>
      <PageHeader
        title="Receiving"
        description="Scan a container, record its condition on arrival, print its labels."
      />

      <form onSubmit={lookUp} className="card" style={{ padding: 16, marginBottom: 16 }}>
        <label htmlFor="sample-code" style={{ display: "block", fontSize: "0.85rem", marginBottom: 6 }}>
          Sample code
        </label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            id="sample-code"
            ref={codeInput}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Scan or type, e.g. WE-202609-0042"
            autoComplete="off"
            spellCheck={false}
            style={{ flex: "1 1 280px", fontFamily: "monospace", fontSize: "1rem" }}
          />
          <button type="submit" className="btn btn-primary" disabled={!code.trim()}>
            Look up
          </button>
          {submitted && (
            <button type="button" className="btn" onClick={startOver}>
              Clear
            </button>
          )}
        </div>
      </form>

      {isFetching && <div className="card card-state">Looking up {submitted}…</div>}

      {isError && (
        <div className="card card-state card-state-error">Couldn't look that code up.</div>
      )}

      {submitted && !isFetching && !isError && !sample && (
        <div className="card card-state">
          No sample with code <strong>{submitted}</strong>. Check the label, or pre-register it first.
        </div>
      )}

      {sample && (
        <ReceivingPanel
          key={sample.id}
          sample={sample}
          mayReceive={mayReceive}
          onDone={startOver}
        />
      )}
    </div>
  );
}

/**
 * One sample, its state, and whatever action it is actually up for.
 *
 * The panel deliberately does not offer every transition: a receiving bench
 * receives things and labels them. A sample that has moved on is shown with
 * its status and a link, not a form — the wrong action taken quickly is
 * worse than the right one taken from the sample screen.
 */
function ReceivingPanel({
  sample,
  mayReceive,
  onDone,
}: {
  sample: Sample;
  mayReceive: boolean;
  onDone: () => void;
}) {
  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ fontSize: "1.15rem", margin: "0 0 4px", fontFamily: "monospace" }}>
            <Link to={`/samples/${sample.id}`}>{sample.unique_sample_code}</Link>
          </h2>
          <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
            {sample.service_line.replace("_", " ")}
            {sample.client_reference && ` · ${sample.client_reference}`}
            {sample.priority !== "routine" && ` · ${SAMPLE_PRIORITY_LABELS[sample.priority]}`}
            {" · "}
            {sample.container_count}× {sample.container_type || "container"}
          </div>
        </div>
        <StatusBadge status={sample.status} />
      </div>

      {sample.status === "registered" && mayReceive && (
        <ReceiptForm sample={sample} onReceived={onDone} />
      )}

      {sample.status === "registered" && !mayReceive && (
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", marginTop: 16 }}>
          Receiving this sample requires the Sample Receiver or Lab Supervisor role.
        </p>
      )}

      {sample.status === "pre_registered" && (
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", marginTop: 16 }}>
          This sample is still pre-registered. Register it on its{" "}
          <Link to={`/samples/${sample.id}`}>sample screen</Link> before receiving it.
        </p>
      )}

      {sample.status !== "registered" && sample.status !== "pre_registered" && (
        <ReceivedSummary sampleId={sample.id} />
      )}

      <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {/* Secondary, deliberately. On a sample still waiting to be
            received the primary act is receiving it, and a bright Print
            button beside a disabled "Receive and print labels" reads as
            the thing to do next -- which would put an identity on a
            container whose condition nobody has recorded yet. */}
        <PrintButton
          path={`/samples/${sample.id}/labels/`}
          sampleId={sample.id}
          label={`Print ${sample.container_count} label${sample.container_count === 1 ? "" : "s"}`}
          reprintPrompt="This sample has already been labelled. Why is it being printed again?"
        />
        <button type="button" className="btn" onClick={onDone}>
          Next sample
        </button>
      </div>
    </div>
  );
}

/**
 * What was recorded when this item arrived, for a sample that is already
 * in.
 *
 * It exists for one case: a clerk records a deviation, looks the code up
 * again an hour later, and sees nothing about it. The item is sitting in a
 * fridge with testing on hold pending a call to the customer, and the
 * receiving desk is exactly who should be making that call — so the hold
 * is said out loud here rather than only on the sample screen.
 *
 * A second request for the detail, because the scan lookup returns list
 * rows and the receipt hangs off the detail. Worth the round trip: it only
 * fires for a sample already received, which is the minority path.
 */
function ReceivedSummary({ sampleId }: { sampleId: number }) {
  const { data } = useSample(sampleId);
  const receipt = data?.receipt;

  if (!receipt || receipt.is_conforming) {
    return (
      <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", marginTop: 16 }}>
        Already received. Labels can still be printed below.
      </p>
    );
  }

  return (
    <div
      style={{
        marginTop: 16,
        border: "1px solid var(--color-danger)",
        background: "var(--color-danger-bg)",
        borderRadius: 6,
        padding: 12,
        fontSize: "0.9rem",
      }}
    >
      <strong style={{ color: "var(--color-danger)" }}>Received with deviations</strong>
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {receipt.deviation_reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      {receipt.consultation_recorded ? (
        <p style={{ margin: "8px 0 0" }}>
          Customer consulted: {receipt.consultation_outcome}
        </p>
      ) : (
        <p style={{ margin: "8px 0 0", color: "var(--color-warning)" }}>
          Testing is on hold until the customer has been consulted and the outcome recorded
          (ISO/IEC 17025:2017 7.4.3).
        </p>
      )}
    </div>
  );
}

/**
 * The ISO/IEC 17025:2017 7.4.3 checklist, presented the way a paper one is:
 * every check phrased as the conforming answer and ticked by default, with
 * the clerk unticking what is wrong.
 *
 * Pre-ticked boxes are usually an ALCOA smell, and the reason they are
 * acceptable here is that the API's default is the same affirmation: a bare
 * POST records a conforming receipt attributed to the person who sent it
 * (see receipt_services.record_receipt). This form makes that affirmation
 * visible rather than implicit, which is strictly better than the endpoint
 * being called with no checklist at all — which is what happens today.
 *
 * The deviations box appears the moment any check fails, because the server
 * refuses a nonconforming receipt without one and there is no reason to let
 * somebody discover that after pressing the button.
 */
function ReceiptForm({ sample, onReceived }: { sample: Sample; onReceived: () => void }) {
  const action = useSampleAction(sample.id);

  const [checks, setChecks] = useState<Record<ReceiptCheckField, boolean>>({
    seal_intact: true,
    volume_sufficient: true,
    container_conforms: true,
    preservation_conforms: true,
    labelling_legible: true,
  });
  const [condition, setCondition] = useState<ReceiptCondition>("intact");
  const [receivedFrom, setReceivedFrom] = useState("");
  const [storageLocation, setStorageLocation] = useState("");
  const [temperature, setTemperature] = useState("");
  const [temperatureConforms, setTemperatureConforms] = useState<"" | "yes" | "no">("");
  const [deviations, setDeviations] = useState("");

  const failedChecks = RECEIPT_CHECKS.filter(({ field }) => !checks[field]);
  const nonConforming =
    condition !== "intact" || failedChecks.length > 0 || temperatureConforms === "no";

  function submit(event: React.FormEvent) {
    event.preventDefault();

    const body: ReceivePayload = {
      ...checks,
      condition_on_receipt: condition,
      received_from: receivedFrom,
      storage_location: storageLocation,
      deviations,
    };
    if (temperature.trim()) body.receipt_temperature_c = temperature.trim();
    if (temperatureConforms) body.temperature_conforms = temperatureConforms === "yes";

    action.mutate(
      { action: "receive", body: body as unknown as Record<string, unknown> },
      { onSuccess: onReceived },
    );
  }

  return (
    <form onSubmit={submit} style={{ marginTop: 16, borderTop: "1px solid var(--color-border)", paddingTop: 16 }}>
      <h3 style={{ fontSize: "0.95rem", margin: "0 0 4px" }}>Condition on receipt</h3>
      <p style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", margin: "0 0 12px" }}>
        Recorded as observed now, while the item is in front of you (ISO/IEC 17025:2017 7.4.3).
      </p>

      <fieldset style={{ border: 0, padding: 0, margin: "0 0 12px" }}>
        <legend className="visually-hidden">Receipt checks</legend>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 20px" }}>
          {RECEIPT_CHECKS.map(({ field, label }) => (
            <label key={field} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.9rem" }}>
              <input
                type="checkbox"
                checked={checks[field]}
                onChange={(e) => setChecks((was) => ({ ...was, [field]: e.target.checked }))}
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
        <label className="field" style={{ flex: "1 1 180px" }}>
          Overall condition
          <select value={condition} onChange={(e) => setCondition(e.target.value as ReceiptCondition)}>
            {Object.entries(RECEIPT_CONDITION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label className="field" style={{ flex: "1 1 140px" }}>
          Temperature °C
          <input
            type="text"
            inputMode="decimal"
            value={temperature}
            onChange={(e) => setTemperature(e.target.value)}
            placeholder="e.g. 4.5"
          />
        </label>

        <label className="field" style={{ flex: "1 1 160px" }}>
          {/* Three states, not a checkbox: blank means no temperature
              requirement applies to this item, which is not the same as
              conforming -- see SampleReceipt.temperature_conforms. */}
          Within specified range?
          <select
            value={temperatureConforms}
            onChange={(e) => setTemperatureConforms(e.target.value as "" | "yes" | "no")}
          >
            <option value="">Not applicable</option>
            <option value="yes">Yes</option>
            <option value="no">No — excursion</option>
          </select>
        </label>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 12 }}>
        <label className="field" style={{ flex: "1 1 220px" }}>
          Received from
          <input
            type="text"
            value={receivedFrom}
            onChange={(e) => setReceivedFrom(e.target.value)}
            placeholder="Courier, sampler or customer rep"
          />
        </label>
        <label className="field" style={{ flex: "1 1 220px" }}>
          Stored at
          <input
            type="text"
            value={storageLocation}
            onChange={(e) => setStorageLocation(e.target.value)}
            placeholder="e.g. Fridge B, shelf 2"
          />
        </label>
      </div>

      {nonConforming && (
        <div
          style={{
            border: "1px solid var(--color-danger)",
            background: "var(--color-danger-bg)",
            borderRadius: 6,
            padding: 12,
            marginBottom: 12,
          }}
        >
          <label style={{ fontSize: "0.85rem", display: "block" }}>
            <strong style={{ color: "var(--color-danger)" }}>Deviations</strong> — required, and
            testing stays on hold until the customer has been consulted (7.4.3).
            <textarea
              value={deviations}
              onChange={(e) => setDeviations(e.target.value)}
              rows={3}
              placeholder="What was wrong with the item as received?"
              style={{ display: "block", width: "100%", marginTop: 6, boxSizing: "border-box" }}
            />
          </label>
        </div>
      )}

      <button
        type="submit"
        className="btn btn-primary"
        disabled={action.isPending || (nonConforming && !deviations.trim())}
      >
        {action.isPending ? "Receiving…" : "Receive and print labels"}
      </button>

      {action.isError && (
        <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 10 }}>
          {describeApiError(action.error)}
        </p>
      )}
    </form>
  );
}
