import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useApproveDocumentVersion, useCreateDocumentVersion, useDocument } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { DOCUMENT_TYPE_LABELS, DOCUMENT_WRITE_ROLES } from "../api/types";
import { PageHeader } from "../components/PageHeader";

export function DocumentDetail() {
  const { id } = useParams<{ id: string }>();
  const documentId = Number(id);
  const { data: doc, isLoading, isError } = useDocument(documentId);
  const { hasRole } = useAuth();
  const canWrite = hasRole(...DOCUMENT_WRITE_ROLES);
  const createVersion = useCreateDocumentVersion(documentId);
  const approveVersion = useApproveDocumentVersion(documentId);

  const nextVersionNumber = doc ? Math.max(0, ...doc.versions.map((v) => v.version_number)) + 1 : 1;
  const [versionNumber, setVersionNumber] = useState(nextVersionNumber);
  const [fileId, setFileId] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");

  // Re-suggest the next version number once the document has actually
  // loaded: nextVersionNumber is 1 by default before that (doc is
  // undefined), and the useState above only captures that default once.
  useEffect(() => {
    setVersionNumber(nextVersionNumber);
  }, [nextVersionNumber]);

  if (isLoading) return <div>Loading…</div>;
  if (isError || !doc) return <div style={{ color: "var(--color-danger)" }}>Couldn't load this document.</div>;

  function submitNewVersion(e: React.FormEvent) {
    e.preventDefault();
    createVersion.mutate(
      { version_number: versionNumber, file_id: fileId, effective_date: effectiveDate || undefined },
      { onSuccess: () => setFileId("") },
    );
  }

  return (
    <div>
      <PageHeader
        back={{ to: "/documents", label: "documents" }}
        title={doc.title}
        meta={
          <span className="badge badge-neutral">
            {DOCUMENT_TYPE_LABELS[doc.type]}
          </span>
        }
      />

      <div className="card" style={{ padding: 20, marginBottom: 20 }}>
        <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Versions</h2>
        {doc.versions.length === 0 ? (
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>No versions yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>File</th>
                <th>Approved by</th>
                <th>Effective</th>
                {canWrite && <th></th>}
              </tr>
            </thead>
            <tbody>
              {doc.versions.map((v) => (
                <tr key={v.id} style={{ cursor: "default" }}>
                  <td style={{ fontWeight: 600 }}>
                    v{v.version_number}
                    {v.is_current && (
                      <span
                        className="badge"
                        style={{ background: "var(--color-success-bg)", color: "var(--color-success)", marginLeft: 8 }}
                      >
                        Current
                      </span>
                    )}
                  </td>
                  <td style={{ fontFamily: "ui-monospace, monospace", fontSize: "0.8rem" }}>{v.file_id}</td>
                  <td>{v.approved_by_display_name || "—"}</td>
                  <td>{v.effective_date || "—"}</td>
                  {canWrite && (
                    <td>
                      {!v.is_current && (
                        <button
                          className="btn btn-primary"
                          disabled={approveVersion.isPending}
                          onClick={() => approveVersion.mutate(v.id)}
                        >
                          Approve
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {approveVersion.isError && (
          <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 12 }}>
            {describeApiError(approveVersion.error)}
          </p>
        )}
      </div>

      {canWrite && (
        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ fontSize: "1rem", margin: "0 0 12px" }}>Add a new version</h2>
          <form onSubmit={submitNewVersion} style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
            <label style={labelStyle}>
              Version #
              <input
                type="number"
                min={1}
                value={versionNumber}
                onChange={(e) => setVersionNumber(Number(e.target.value))}
                required
                style={{ width: 80 }}
              />
            </label>
            <label style={{ ...labelStyle, flex: 1, minWidth: 220 }}>
              File (OSS object key)
              <input
                value={fileId}
                onChange={(e) => setFileId(e.target.value)}
                placeholder="oss://documents/sop-123-v2.pdf"
                required
              />
            </label>
            <label style={labelStyle}>
              Effective date (optional)
              <input type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
            </label>
            <button type="submit" className="btn btn-primary" disabled={createVersion.isPending}>
              Add version
            </button>
          </form>
          {createVersion.isError && (
            <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 10 }}>
              {describeApiError(createVersion.error)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

const labelStyle = { display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" } as const;
