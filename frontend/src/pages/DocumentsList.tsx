import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateDocument, useDocuments } from "../api/queries";
import { useAuth } from "../auth/context";
import { describeApiError } from "../api/client";
import { PageHeader } from "../components/PageHeader";
import { DOCUMENT_TYPE_LABELS, DOCUMENT_WRITE_ROLES } from "../api/types";
import type { DocumentType } from "../api/types";

const DOCUMENT_TYPES = Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[];

export function DocumentsList() {
  const { data, isLoading, isError } = useDocuments();
  const { hasRole } = useAuth();
  const canWrite = hasRole(...DOCUMENT_WRITE_ROLES);
  const createDocument = useCreateDocument();
  const navigate = useNavigate();

  const [title, setTitle] = useState("");
  const [type, setType] = useState<DocumentType>("sop");

  function submitNewDocument(e: React.FormEvent) {
    e.preventDefault();
    createDocument.mutate(
      { title, type },
      {
        onSuccess: (doc) => {
          setTitle("");
          navigate(`/documents/${doc.id}`);
        },
      },
    );
  }

  return (
    <div>
      <PageHeader title="Documents" description="SOPs, manuals, forms, and other controlled documents (FR-D1-02)." />

      {canWrite && (
        <form
          onSubmit={submitNewDocument}
          className="card"
          style={{ padding: 16, marginBottom: 20, display: "flex", gap: 10, alignItems: "flex-end" }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem", flex: 1 }}>
            New document title
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: "0.8rem" }}>
            Type
            <select value={type} onChange={(e) => setType(e.target.value as DocumentType)}>
              {DOCUMENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {DOCUMENT_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={createDocument.isPending}>
            Create
          </button>
          {createDocument.isError && (
            <span style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{describeApiError(createDocument.error)}</span>
          )}
        </form>
      )}

      <div className="card table-card">
        {isLoading && <div className="card-state">Loading…</div>}
        {isError && <div className="card-state card-state-error">Couldn't load documents.</div>}
        {data && data.results.length === 0 && (
          <div className="card-state">No documents yet.</div>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Current version</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((doc) => (
                <tr key={doc.id} onClick={() => navigate(`/documents/${doc.id}`)}>
                  <td style={{ fontWeight: 600 }}>{doc.title}</td>
                  <td>{DOCUMENT_TYPE_LABELS[doc.type]}</td>
                  <td>{doc.current_version_number !== null ? `v${doc.current_version_number}` : "None approved yet"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

