/**
 * Document detail: version control and FR-D1-03 approval.
 *
 * Approving a version archives whichever version was current and repoints
 * Document.current_version — a server-side side effect on a *different* row
 * than the one acted on. The screen therefore cannot patch state locally; it
 * has to re-read the document, or the table shows two versions both badged
 * "Current", which for a controlled SOP is the worst possible display.
 */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DocumentDetail } from "./DocumentDetail";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";

function version(overrides = {}) {
  return {
    id: 20,
    document: 6,
    version_number: 1,
    file_id: "sops/sop-001-v1.pdf",
    approved_by: 1,
    approved_by_display_name: "QA Officer",
    effective_date: "2026-01-01",
    is_current: true,
    created_at: "2026-01-01T09:00:00Z",
    ...overrides,
  };
}

function document(versions = [version()]) {
  return {
    id: 6,
    title: "SOP-001 Sample Reception",
    type: "sop",
    current_version: versions.find((v) => v.is_current)?.id ?? null,
    current_version_number: versions.find((v) => v.is_current)?.version_number ?? null,
    created_at: "2026-01-01T09:00:00Z",
    versions,
  };
}

function render(user = staffUser({ roles: [role("qa_officer")] }), doc = document(), extra = {}) {
  const stub = stubApi({
    "/auth/staff/me": { body: user },
    "/documents/6/": { body: doc },
    ...extra,
  });
  renderWithProviders(<DocumentDetail />, { route: "/documents/6", path: "/documents/:id" });
  return stub;
}

const TWO_VERSIONS = [
  version({ id: 20, version_number: 1, is_current: true }),
  version({ id: 21, version_number: 2, is_current: false, approved_by: null, approved_by_display_name: null }),
];

describe("the write gate", () => {
  it("hides approval and the new-version form from an analyst", async () => {
    render(staffUser({ roles: [role("analyst")] }), document(TWO_VERSIONS));
    await screen.findByText("SOP-001 Sample Reception");

    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add version" })).not.toBeInTheDocument();
  });

  it("shows them to a QA officer", async () => {
    render(undefined, document(TWO_VERSIONS));
    await screen.findByText("SOP-001 Sample Reception");

    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add version" })).toBeInTheDocument();
  });

  it("shows them to a lab supervisor", async () => {
    render(staffUser({ roles: [role("lab_supervisor")] }), document(TWO_VERSIONS));

    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
  });
});

describe("approving a version", () => {
  it("offers approval only on versions that are not already current", async () => {
    // Re-approving the current version is a no-op the server would have to
    // reject; not offering it is simpler than explaining it.
    render(undefined, document(TWO_VERSIONS));
    await screen.findByText("SOP-001 Sample Reception");

    // One button for the non-current v2, none for the current v1.
    expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(1);
  });

  it("posts against the version, not the document", async () => {
    const { calls } = render(undefined, document(TWO_VERSIONS), {
      "POST /document-versions/21/approve/": { body: version({ id: 21, version_number: 2, is_current: true }) },
    });
    await screen.findByText("SOP-001 Sample Reception");

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.url).toContain("/document-versions/21/approve/");
  });

  it("re-reads the document afterwards rather than patching one row", async () => {
    // FR-D1-03 archives the previously-current version, a change to a
    // different row than the one approved. Only a re-read sees it.
    const { calls } = render(undefined, document(TWO_VERSIONS), {
      "POST /document-versions/21/approve/": { body: version({ id: 21, version_number: 2, is_current: true }) },
    });
    await screen.findByText("SOP-001 Sample Reception");
    const readsBefore = calls.filter((c) => c.method === "GET" && c.url.includes("/documents/6/")).length;

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => {
      const readsAfter = calls.filter((c) => c.method === "GET" && c.url.includes("/documents/6/")).length;
      expect(readsAfter).toBeGreaterThan(readsBefore);
    });
  });

  it("surfaces the server's rejection", async () => {
    render(undefined, document(TWO_VERSIONS), {
      "POST /document-versions/21/approve/": {
        status: 400,
        body: { detail: "A version with no file_id cannot be approved." },
      },
    });
    await screen.findByText("SOP-001 Sample Reception");

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("A version with no file_id cannot be approved.")).toBeInTheDocument();
  });
});

describe("adding a version", () => {
  it("suggests the next version number once the document has loaded", async () => {
    // The default is 1 before the fetch resolves, and useState captures that
    // once — the component re-syncs in an effect. Getting this wrong offers
    // v1 against a document that is already on v2, which the server rejects
    // as a duplicate.
    render(undefined, document(TWO_VERSIONS));
    await screen.findByText("SOP-001 Sample Reception");

    expect(await screen.findByDisplayValue("3")).toBeInTheDocument();
  });

  it("omits effective_date when left blank rather than sending an empty string", async () => {
    const { calls } = render(undefined, document(TWO_VERSIONS), {
      "POST /document-versions/": { status: 201, body: version({ id: 22, version_number: 3 }) },
    });
    await screen.findByText("SOP-001 Sample Reception");

    await userEvent.type(screen.getByLabelText("File (OSS object key)"), "sops/sop-001-v3.pdf");
    await userEvent.click(screen.getByRole("button", { name: "Add version" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST");
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toMatchObject({ version_number: 3, file_id: "sops/sop-001-v3.pdf" });
    expect(post.body).not.toHaveProperty("effective_date");
  });
});

describe("the version table", () => {
  it("badges exactly one version as current", async () => {
    // Two "Current" badges on a controlled SOP is the display failure the
    // re-read above exists to prevent.
    render(undefined, document(TWO_VERSIONS));
    await screen.findByText("SOP-001 Sample Reception");

    expect(screen.getAllByText("Current")).toHaveLength(1);
  });

  it("shows who approved each version", async () => {
    render(undefined, document(TWO_VERSIONS));
    await screen.findByText("SOP-001 Sample Reception");

    const table = screen.getByRole("table");
    expect(within(table).getByText("QA Officer")).toBeInTheDocument();
    // An unapproved version shows an em dash rather than a blank cell.
    expect(within(table).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("surfaces a load failure", async () => {
    stubApi({
      "/auth/staff/me": { body: staffUser() },
      "/documents/6/": { status: 500, body: { detail: "boom" } },
    });
    renderWithProviders(<DocumentDetail />, { route: "/documents/6", path: "/documents/:id" });

    expect(await screen.findByText("Couldn't load this document.")).toBeInTheDocument();
  });
});
