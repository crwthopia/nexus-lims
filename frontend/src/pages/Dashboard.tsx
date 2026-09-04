import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDashboard } from "../api/queries";
import { PageHeader } from "../components/PageHeader";
import { StatTile } from "../components/StatTile";
import { BarList } from "../components/charts/BarList";
import { ColumnChart } from "../components/charts/ColumnChart";
import { MixBar } from "../components/charts/MixBar";
import { SERVICE_LINE_LABELS } from "../api/types";
import { formatMoney } from "../money";

/**
 * What the lab is doing, and which analyses are carrying it.
 *
 * **Every money figure here is list-price value, not revenue**, and the
 * screen says so rather than leaving the reader to assume. An Order has no
 * line items yet and `Invoice.amount` is a typed lump sum, so nothing in
 * the database records what was actually billed for a given analysis. What
 * *can* be computed honestly is work performed x the rate in force on the
 * day it was requested -- a real answer to "what is this bench worth", and
 * not the same as money received. The distinction is one word wide and
 * would be the easiest thing on this screen to get wrong.
 *
 * The other deliberate exposure is the unattributed count: requests whose
 * method belongs to no offering, or to several, are shown as a number with
 * a way to act on it, rather than dropped (understating the bench) or
 * spread evenly (inventing the split).
 */

const RANGES = [
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
  { label: "12 months", days: 365 },
];

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - (days - 1));
  return date.toISOString().slice(0, 10);
}

/**
 * "Jul", or "Jul 26" when the window spans more than one year -- a
 * twelve-month view whose axis reads Jan..Dec twice is unreadable.
 */
function monthLabel(month: string, all: { month: string }[]): string {
  const [year, index] = month.split("-");
  const spansYears = new Set(all.map((row) => row.month.slice(0, 4))).size > 1;
  const name = new Date(Number(year), Number(index) - 1, 1).toLocaleDateString("en", { month: "short" });
  return spansYears ? `${name} ${year.slice(2)}` : name;
}

function delta(current: number, previous: number, label: string) {
  // No previous work means no comparison to draw -- a "+100%" against zero
  // is arithmetic, not information.
  if (!previous) return null;
  return { pct: ((current - previous) / previous) * 100, label };
}

type Rank = "volume" | "value";

export function Dashboard() {
  const [days, setDays] = useState(90);
  const [rank, setRank] = useState<Rank>("volume");
  const { data, isLoading, isError } = useDashboard({ from: isoDaysAgo(days), rank });
  const navigate = useNavigate();

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Demand, turnaround and quality across the lab. List price is what the work is worth at the rate card; billed is what invoices actually say."
        actions={
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="btn"
            aria-label="Reporting period"
          >
            {RANGES.map((range) => (
              <option key={range.days} value={range.days}>
                Last {range.label}
              </option>
            ))}
          </select>
        }
      />

      {isLoading && <div className="card card-state">Loading the dashboard…</div>}
      {isError && <div className="card card-state card-state-error">Couldn't load the dashboard.</div>}

      {data && (
        <>
          <div className="stat-row">
            <StatTile
              label="Samples received"
              value={data.totals.samples_received.toLocaleString()}
              delta={delta(data.totals.samples_received, data.previous_totals.samples_received, "on the previous period")}
              hint={`${data.window.days} days to ${data.window.to}`}
            />
            <StatTile
              label="Tests requested"
              value={data.totals.test_requests.toLocaleString()}
              delta={delta(data.totals.test_requests, data.previous_totals.test_requests, "on the previous period")}
            />
            <StatTile
              label="List-price value"
              value={formatMoney(data.totals.list_value_net, data.totals.currency)}
              delta={delta(
                Number(data.totals.list_value_net),
                Number(data.previous_totals.list_value_net),
                "on the previous period",
              )}
              hint="net of VAT, at the rate in force"
            />
            <StatTile
              label="Billed"
              value={formatMoney(data.totals.billed_net, data.totals.currency)}
              delta={delta(
                Number(data.totals.billed_net),
                Number(data.previous_totals.billed_net),
                "on the previous period",
              )}
              // Deliberately beside list price rather than replacing it:
              // billed is real money but only for work already invoiced,
              // which lags the bench by however long billing takes.
              hint={`net of VAT, ${data.totals.invoice_lines.toLocaleString()} invoice line${
                data.totals.invoice_lines === 1 ? "" : "s"
              }`}
            />
            <StatTile
              label="Turnaround (median)"
              value={data.turnaround.median_days === null ? "—" : `${data.turnaround.median_days} d`}
              hint={
                data.turnaround.median_days === null
                  ? "nothing approved in this period"
                  : `p90 ${data.turnaround.p90_days} d · ${data.turnaround.sample_count} approved`
              }
            />
          </div>

          <div className="dashboard-grid">
            <div className="stack">
              <div className="card">
                <div className="card-head">
                  <div>
                    <h2>Leading analyses</h2>
                    <p>
                      {rank === "volume"
                        ? "By tests requested, over the last "
                        : "By what the work is worth at list price, over the last "}
                      {data.window.days} days.
                    </p>
                  </div>
                  {/*
                    The two rankings are different answers, not two views of
                    one: the panel run three hundred times fills the bench,
                    the characterisation run forty times at ten times the
                    price pays for it. Switching re-asks the server, because
                    it changes which offerings make the list at all.
                  */}
                  <select
                    value={rank}
                    onChange={(e) => setRank(e.target.value as Rank)}
                    className="btn btn-sm"
                    aria-label="Rank leading analyses by"
                  >
                    <option value="volume">By volume</option>
                    <option value="value">By value</option>
                  </select>
                </div>
                <div className="card-body">
                  <BarList
                    emptyMessage="No test requests in this period."
                    rows={[
                      // The bar length encodes whichever measure is ranking,
                      // so the ordering and the picture always agree.
                      ...data.leading_analyses.map((row) => ({
                        key: row.code,
                        label: row.name,
                        sublabel: row.code,
                        value: rank === "value" ? Number(row.list_value_net) : row.request_count,
                        display: `${row.request_count.toLocaleString()} · ${formatMoney(row.list_value_net)}`,
                        detail:
                          Number(row.billed_net) > 0
                            ? `${SERVICE_LINE_LABELS[row.service_line]} · ${formatMoney(row.billed_net)} billed`
                            : SERVICE_LINE_LABELS[row.service_line],
                      })),
                      ...(data.leading_analyses_other.offering_count > 0
                        ? [
                            {
                              key: "other",
                              label: `${data.leading_analyses_other.offering_count} other offerings`,
                              value:
                                rank === "value"
                                  ? Number(data.leading_analyses_other.list_value_net)
                                  : data.leading_analyses_other.request_count,
                              display: `${data.leading_analyses_other.request_count.toLocaleString()} · ${formatMoney(
                                data.leading_analyses_other.list_value_net,
                              )}`,
                              muted: true,
                            },
                          ]
                        : []),
                    ]}
                  />
                  <UnattributedNote data={data} onFix={() => navigate("/catalogue")} />
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <div>
                    <h2>Tests requested per month</h2>
                    <p>Volume over the reporting period. Hover a column for its list-price value.</p>
                  </div>
                </div>
                <div className="card-body">
                  <ColumnChart
                    emptyMessage="No test requests in this period."
                    columns={data.monthly.map((row) => ({
                      label: monthLabel(row.month, data.monthly),
                      value: row.request_count,
                      display: `${row.request_count.toLocaleString()} tests requested`,
                      detail: `${formatMoney(row.list_value_net)} at list price`,
                    }))}
                  />
                </div>
              </div>
            </div>

            <div className="stack">
              <div className="card">
                <div className="card-head">
                  <div>
                    <h2>Service line mix</h2>
                    <p>Samples received in this period.</p>
                  </div>
                </div>
                <div className="card-body">
                  <MixBar
                    unit="samples"
                    emptyMessage="No samples received in this period."
                    segments={data.service_line_mix.map((row) => ({
                      key: row.service_line,
                      label: SERVICE_LINE_LABELS[row.service_line] ?? row.label,
                      value: row.sample_count,
                    }))}
                  />
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <div>
                    <h2>Turnaround by service line</h2>
                    <p>Days from a sample arriving to its approval, for samples approved in this period.</p>
                  </div>
                </div>
                <div className="card-body">
                  {data.turnaround.by_service_line.length === 0 ? (
                    <p className="card-state" style={{ padding: 0 }}>
                      Nothing was approved in this period.
                    </p>
                  ) : (
                    <dl className="field-grid">
                      {data.turnaround.by_service_line.map((row) => (
                        <Row
                          key={row.service_line}
                          label={SERVICE_LINE_LABELS[row.service_line] ?? row.service_line}
                          value={`${row.median_days} d median · ${row.p90_days} d p90`}
                        />
                      ))}
                    </dl>
                  )}
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <div>
                    <h2>Quality and queues</h2>
                    {/* Rates are for the period; queue depths are current
                        state. A count of "open investigations over the last
                        90 days" would mean nothing, so the two are labelled
                        differently rather than mixed. */}
                    <p>Out-of-spec is for the period; the queues are where things stand now.</p>
                  </div>
                </div>
                <div className="card-body">
                  <dl className="field-grid">
                    <Row
                      label="Out of spec"
                      value={
                        data.quality.out_of_spec_pct === null
                          ? "no results entered"
                          : `${data.quality.out_of_spec_pct}% of ${data.quality.results_entered.toLocaleString()}`
                      }
                    />
                    <Row label="Open investigations" value={String(data.quality.open_investigations)} />
                    <Row label="Awaiting review" value={String(data.quality.samples_awaiting_review)} />
                    <Row label="Instruments out of calibration" value={String(data.quality.instruments_out_of_calibration)} />
                    <Row label="Open system failures" value={String(data.quality.open_system_failures)} />
                  </dl>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * The requests the dashboard could not credit to an offering, and why.
 *
 * Shown rather than hidden because every one of them is a gap in the rate
 * card mapping, and the fix is a click away. Silence here would make the
 * leading-analyses list look complete when it is not.
 */
function UnattributedNote({
  data,
  onFix,
}: {
  data: { unattributed_requests: { no_offering: number; ambiguous: number; unpriced: number } };
  onFix: () => void;
}) {
  const { no_offering, ambiguous, unpriced } = data.unattributed_requests;
  const total = no_offering + ambiguous + unpriced;
  if (total === 0) return null;

  const reasons = [
    no_offering > 0 && `${no_offering} on methods in no offering`,
    ambiguous > 0 && `${ambiguous} on methods sold under more than one`,
    unpriced > 0 && `${unpriced} on offerings with no price that day`,
  ].filter(Boolean);

  return (
    <p style={{ marginTop: 20, marginBottom: 0, color: "var(--color-text-muted)", fontSize: "0.82rem" }}>
      {total.toLocaleString()} request{total === 1 ? "" : "s"} above the ranking isn't counted against any offering:{" "}
      {reasons.join(", ")}.{" "}
      <button type="button" className="btn btn-sm" style={{ marginLeft: 4 }} onClick={onFix}>
        Fix in the catalogue
      </button>
    </p>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", padding: "6px 0" }}>{label}</dt>
      <dd style={{ margin: 0, padding: "6px 0" }}>{value}</dd>
    </>
  );
}
