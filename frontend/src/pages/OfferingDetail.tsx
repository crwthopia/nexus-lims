import { useState } from "react";
import { useParams } from "react-router-dom";
import { useServiceOffering, useSetOfferingPrice, useUpdateServiceOffering } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { CATALOGUE_WRITE_ROLES, SERVICE_LINE_LABELS, VAT_TREATMENT_LABELS } from "../api/types";
import type { OfferingPrice, VatTreatment } from "../api/types";
import { formatMoney } from "../money";

/**
 * One catalogue entry, and its price history.
 *
 * The history is the screen's reason for existing. A price is superseded,
 * never edited, so "what did we charge in March" has an answer here rather
 * than in someone's inbox -- and repricing is a form that states the date
 * it takes effect, because that is the field people get wrong when the only
 * choice on offer is "now".
 */
export function OfferingDetail() {
  const { id } = useParams<{ id: string }>();
  const offeringId = Number(id);
  const { data: offering, isLoading, isError } = useServiceOffering(offeringId);
  const { hasRole } = useAuth();
  const canWrite = hasRole(...CATALOGUE_WRITE_ROLES);

  const setPrice = useSetOfferingPrice(offeringId);
  const updateOffering = useUpdateServiceOffering(offeringId);

  const [amount, setAmount] = useState("");
  const [treatment, setTreatment] = useState<VatTreatment>("exclusive");
  const [vatRate, setVatRate] = useState("12.00");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [note, setNote] = useState("");

  if (isLoading) return <div className="card-state">Loading…</div>;
  if (isError || !offering) return <div className="card-state card-state-error">Couldn't load this offering.</div>;

  function submitPrice(e: React.FormEvent) {
    e.preventDefault();
    setPrice.mutate(
      {
        amount,
        vat_treatment: treatment,
        vat_rate_pct: vatRate,
        // Omitted rather than sent empty: the server defaults to today,
        // and "" is not a date.
        ...(effectiveFrom ? { effective_from: effectiveFrom } : {}),
        ...(note ? { note } : {}),
      },
      {
        onSuccess: () => {
          setAmount("");
          setNote("");
        },
      },
    );
  }

  const current = offering.current_price;

  return (
    <div>
      <PageHeader
        back={{ to: "/catalogue", label: "catalogue" }}
        title={`${offering.code} — ${offering.name}`}
        meta={
          <>
            <span className="badge badge-neutral">{SERVICE_LINE_LABELS[offering.service_line]}</span>
            {offering.is_accredited && <span className="badge badge-neutral">Accredited</span>}
            {!offering.is_active && <span className="badge badge-neutral">Withdrawn</span>}
          </>
        }
      />

      <div className="detail-grid">
        <div className="stack">
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Current price</h2>
            {current ? (
              <dl className="field-grid">
                <Field label="As quoted" value={`${formatMoney(current.amount, current.currency)} ${current.vat_treatment === "inclusive" ? "incl. VAT" : "excl. VAT"}`} />
                <Field label="VAT rate" value={`${current.vat_rate_pct}%`} />
                <Field label="Net" value={formatMoney(current.net_amount, current.currency)} />
                <Field label="VAT" value={formatMoney(current.vat_amount, current.currency)} />
                <Field label="Gross" value={formatMoney(current.gross_amount, current.currency)} />
                <Field label="In force since" value={current.effective_from} />
              </dl>
            ) : (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", margin: 0 }}>
                Not priced today. {offering.prices.length > 0 ? "See the history below." : "Set a price to sell it."}
              </p>
            )}

            <h2 style={{ fontSize: "1rem", margin: "24px 0 12px" }}>Details</h2>
            <dl className="field-grid">
              <Field label="Turnaround" value={offering.turnaround_days ? `${offering.turnaround_days} working days` : "—"} />
              <Field label="Test methods" value={offering.test_method_names.join(", ") || "Not mapped yet"} />
            </dl>
            {offering.description && (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", marginBottom: 0 }}>{offering.description}</p>
            )}
          </div>

          <div className="card table-card">
            <div className="card-head">
              <div>
                <h2>Price history</h2>
                <p>Every rate this offering has carried, and when. Prices are superseded, never edited.</p>
              </div>
            </div>
            {offering.prices.length === 0 ? (
              <div className="card-state">No price has been set yet.</div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>From</th>
                    <th>To</th>
                    <th>As quoted</th>
                    <th>Net</th>
                    <th>Gross</th>
                    <th>Set by</th>
                  </tr>
                </thead>
                <tbody>
                  {offering.prices.map((price: OfferingPrice) => (
                    <tr key={price.id} style={{ cursor: "default" }}>
                      <td>{price.effective_from}</td>
                      <td>{price.effective_to ?? "current"}</td>
                      <td>
                        {formatMoney(price.amount, price.currency)}{" "}
                        <span style={{ color: "var(--color-text-muted)" }}>
                          {price.vat_treatment === "inclusive" ? "incl." : "excl."}
                        </span>
                      </td>
                      <td>{formatMoney(price.net_amount, price.currency)}</td>
                      <td>{formatMoney(price.gross_amount, price.currency)}</td>
                      <td style={{ color: "var(--color-text-muted)" }}>
                        {price.created_by_display_name ?? "—"}
                        {price.note && ` — ${price.note}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="stack">
          <div className="card" style={{ padding: 20 }}>
            <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Set a price</h2>
            {!canWrite ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem", margin: 0 }}>
                Requires role: {CATALOGUE_WRITE_ROLES.join(" or ")}.
              </p>
            ) : (
              <form onSubmit={submitPrice} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <label className="field">
                  Amount
                  <input value={amount} onChange={(e) => setAmount(e.target.value)} required placeholder="1200.00" />
                </label>
                <label className="field">
                  Quoted
                  <select value={treatment} onChange={(e) => setTreatment(e.target.value as VatTreatment)}>
                    {(Object.keys(VAT_TREATMENT_LABELS) as VatTreatment[]).map((value) => (
                      <option key={value} value={value}>
                        {VAT_TREATMENT_LABELS[value]}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  VAT rate (%)
                  <input value={vatRate} onChange={(e) => setVatRate(e.target.value)} />
                </label>
                <label className="field">
                  Effective from
                  <input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
                </label>
                <label className="field">
                  Note
                  <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="2026 rate card" />
                </label>
                <button type="submit" className="btn btn-primary" disabled={setPrice.isPending}>
                  {current ? "Supersede price" : "Set price"}
                </button>
                {setPrice.isError && (
                  <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", margin: 0 }}>
                    {describeApiError(setPrice.error)}
                  </p>
                )}
                <p style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", margin: 0 }}>
                  Leave the date blank for today. The price in force is closed the day before this one starts, so past
                  invoices keep quoting the rate they were raised at.
                </p>
              </form>
            )}
          </div>

          {canWrite && (
            <div className="card" style={{ padding: 20 }}>
              <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Availability</h2>
              <button
                type="button"
                className="btn"
                style={{ width: "100%" }}
                disabled={updateOffering.isPending}
                onClick={() => updateOffering.mutate({ is_active: !offering.is_active })}
              >
                {offering.is_active ? "Withdraw from the catalogue" : "Return to the catalogue"}
              </button>
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", margin: "10px 0 0" }}>
                A withdrawn offering stops being sold but stays here: past orders reference it, and its price history is
                part of the record.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", padding: "6px 0" }}>{label}</dt>
      <dd style={{ margin: 0, padding: "6px 0" }}>{value}</dd>
    </>
  );
}
