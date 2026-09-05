import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateServiceOffering, useServiceOfferings } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { CATALOGUE_SERVICE_LINES, CATALOGUE_WRITE_ROLES, SERVICE_LINE_LABELS } from "../api/types";
import type { ServiceLine } from "../api/types";
import { formatMoney } from "../money";

/**
 * The rate card: what the lab sells, and for how much.
 *
 * The list shows net *and* gross for every offering rather than the figure
 * as published, because NASAT quotes some rates VAT-exclusive and some
 * VAT-inclusive -- a column of raw `amount`s would put ₱1,000 net beside
 * ₱1,120 gross and invite the reader to compare them. The server computes
 * all three figures (backend/apps/catalogue/models.py); this only labels
 * which way each one was quoted.
 */
export function CatalogueList() {
  const { hasRole } = useAuth();
  const canWrite = hasRole(...CATALOGUE_WRITE_ROLES);
  const navigate = useNavigate();

  const [serviceLine, setServiceLine] = useState("");
  const [search, setSearch] = useState("");
  const { data, isLoading, isError } = useServiceOfferings({
    service_line: serviceLine || undefined,
    q: search || undefined,
  });
  const createOffering = useCreateServiceOffering();

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [newLine, setNewLine] = useState<ServiceLine>("water_environmental");

  function submitOffering(e: React.FormEvent) {
    e.preventDefault();
    createOffering.mutate(
      { code, name, service_line: newLine },
      {
        onSuccess: (offering) => {
          setCode("");
          setName("");
          navigate(`/catalogue/${offering.id}`);
        },
      },
    );
  }

  return (
    <div>
      <PageHeader
        title="Catalogue"
        description="Analyses and panels the lab sells, with the rate in force today. Training is priced in its own catalogue."
        actions={
          <>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search code or name"
              aria-label="Search the catalogue"
              style={{ width: 200 }}
            />
            <select
              value={serviceLine}
              onChange={(e) => setServiceLine(e.target.value)}
              className="btn"
              aria-label="Filter by service line"
            >
              <option value="">All service lines</option>
              {CATALOGUE_SERVICE_LINES.map((line) => (
                <option key={line} value={line}>
                  {SERVICE_LINE_LABELS[line]}
                </option>
              ))}
            </select>
          </>
        }
      />

      {canWrite && (
        <form
          onSubmit={submitOffering}
          className="card"
          style={{ padding: 16, marginBottom: 20, display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <label className="field" style={{ width: 160 }}>
            Code
            <input value={code} onChange={(e) => setCode(e.target.value)} required placeholder="WQ-BOD5" />
          </label>
          <label className="field" style={{ flex: 1, minWidth: 200 }}>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="BOD (5-day)" />
          </label>
          <label className="field">
            Service line
            <select value={newLine} onChange={(e) => setNewLine(e.target.value as ServiceLine)}>
              {CATALOGUE_SERVICE_LINES.map((line) => (
                <option key={line} value={line}>
                  {SERVICE_LINE_LABELS[line]}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={createOffering.isPending}>
            Add offering
          </button>
          {/* Pricing happens on the detail screen: an offering is created
              once and repriced many times, and folding a price into this
              form would imply the two are one act. */}
          {createOffering.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", margin: 0, width: "100%" }}>
              {describeApiError(createOffering.error)}
            </p>
          )}
        </form>
      )}

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading the catalogue…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load the catalogue.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">
            Nothing in the catalogue matches this filter.
            {canWrite && " Add an offering above, or import a rate card with manage.py import_price_list."}
          </div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Offering</th>
                <th>Service line</th>
                <th>Net</th>
                <th>Gross (incl. VAT)</th>
                <th>Quoted</th>
                <th>TAT</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((offering) => (
                <tr key={offering.id} onClick={() => navigate(`/catalogue/${offering.id}`)}>
                  <td style={{ fontWeight: 600 }}>{offering.code}</td>
                  <td>
                    {offering.name}
                    {!offering.is_active && <span className="badge badge-neutral" style={{ marginLeft: 8 }}>Withdrawn</span>}
                    {offering.is_accredited && (
                      <span className="badge badge-neutral" style={{ marginLeft: 8 }} title="Within the ISO/IEC 17025 scope">
                        Accredited
                      </span>
                    )}
                  </td>
                  <td>{SERVICE_LINE_LABELS[offering.service_line]}</td>
                  <td>{offering.current_price ? formatMoney(offering.current_price.net_amount) : "—"}</td>
                  <td>{offering.current_price ? formatMoney(offering.current_price.gross_amount) : "—"}</td>
                  <td style={{ color: "var(--color-text-muted)" }}>
                    {offering.current_price ? (offering.current_price.vat_treatment === "inclusive" ? "incl." : "excl.") : "not priced"}
                  </td>
                  <td>{offering.turnaround_days ? `${offering.turnaround_days} d` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && (
        <div style={{ marginTop: 12, color: "var(--color-text-muted)", fontSize: "0.85rem" }}>{data.count} total</div>
      )}
    </div>
  );
}
