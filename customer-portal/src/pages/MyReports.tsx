import { useState } from "react";
import { useMyReports, useReportDownloadUrl } from "../api/queries";
import { REPORT_TYPE_LABELS } from "../api/types";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";

/**
 * A customer's own certificates and reports.
 *
 * Downloads go through a presigned URL fetched at click time, not a link
 * rendered on load: the URLs expire, so minting them up front produces links
 * that silently fail on a page left open. The click fetches, then navigates
 * the browser to the returned URL.
 */
export function MyReports() {
  const { data, isLoading, isError } = useMyReports();
  const download = useReportDownloadUrl();
  const [failedId, setFailedId] = useState<number | null>(null);

  function onDownload(reportId: number) {
    setFailedId(null);
    download.mutate(reportId, {
      onSuccess: ({ url }) => {
        // assign() rather than window.open(): a popup blocker will stop an
        // open() that isn't recognised as directly user-initiated, and this
        // one happens after an await.
        window.location.assign(url);
      },
      onError: () => setFailedId(reportId),
    });
  }

  return (
    <div>
      <PageHeader title="My Reports" description="Certificates of analysis and training certificates issued to you." />

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && (
          <div className="card-state card-state-error">Couldn't load your reports.</div>
        )}
        {data && data.results.length === 0 && (
          <div className="card-state">
            No reports yet. A certificate appears here once your sample has been approved and its
            report issued.
          </div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Report</th>
                <th>Sample</th>
                <th>Issued</th>
                <th>Version</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.results.map((report) => (
                <tr key={report.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>{REPORT_TYPE_LABELS[report.report_type]}</td>
                  <td>{report.sample_code ?? "—"}</td>
                  <td>{new Date(report.generated_at).toLocaleDateString()}</td>
                  <td>v{report.version}</td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="btn"
                      disabled={download.isPending && download.variables === report.id}
                      onClick={() => onDownload(report.id)}
                    >
                      {download.isPending && download.variables === report.id
                        ? "Preparing…"
                        : "Download PDF"}
                    </button>
                    {failedId === report.id && (
                      <div style={{ color: "var(--color-danger)", fontSize: "0.8rem", marginTop: 6 }}>
                        {describeApiError(download.error)}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
