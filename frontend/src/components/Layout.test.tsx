/**
 * The console shell.
 *
 * Three things here are load-bearing and none of them is visual:
 *
 * - the rail must not offer a destination the caller's roles can't open.
 *   The gate is `navSections`, shared with the command palette, so a
 *   regression shows up in both places at once -- which is exactly why the
 *   nav is one list rather than JSX in two files;
 * - the collapse must survive a reload, and must survive `localStorage`
 *   being unavailable, which throws on *access* in private browsing;
 * - Ctrl-K has to reach the palette from anywhere in the app, including
 *   from inside a text field, since that is where a cursor usually is.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Layout } from "./Layout";
import { renderWithProviders, role, staffUser, stubApi } from "../test/helpers";
import { SIDEBAR_STORAGE_KEY } from "../sidebar";

beforeEach(() => {
  localStorage.clear();
});

function renderShell(user = staffUser()) {
  stubApi({ "/auth/staff/me": { body: user } });
  return renderWithProviders(<Layout />, { route: "/samples", path: "/samples" });
}

describe("Layout", () => {
  it("groups the destinations under section headings", async () => {
    renderShell();

    expect(await screen.findByRole("link", { name: "Samples" })).toBeInTheDocument();
    // The group's accessible name comes from the <ul>, since the visible
    // heading above it is hidden when the rail collapses to icons.
    expect(screen.getByRole("list", { name: "Quality" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Commercial" })).toBeInTheDocument();
  });

  it("hides the queues a user's roles cannot open", async () => {
    renderShell(staffUser({ roles: [role("sample_receiver")] }));

    await screen.findByRole("link", { name: "Samples" });
    expect(screen.queryByRole("link", { name: "Review Queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Testing Queue" })).not.toBeInTheDocument();
  });

  it("shows the review queue to a reviewer", async () => {
    renderShell(staffUser({ roles: [role("reviewer")] }));

    expect(await screen.findByRole("link", { name: "Review Queue" })).toBeInTheDocument();
  });

  it("remembers a collapsed rail", async () => {
    renderShell();

    await userEvent.click(await screen.findByRole("button", { name: "Collapse sidebar" }));

    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("collapses even when localStorage refuses to remember it", async () => {
    // Private browsing and "block site data" throw on write. The rail still
    // has to move; it just won't be that way on the next visit.
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("The operation is insecure.");
    });
    renderShell();

    await userEvent.click(await screen.findByRole("button", { name: "Collapse sidebar" }));

    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("names the screen in the header", async () => {
    stubApi({ "/auth/staff/me": { body: staffUser() } });
    renderWithProviders(<Layout />, { route: "/samples/8", path: "/samples/:id" });

    // A detail route names the section it belongs to; the record's own
    // identity is the page's <h1>, not the header's.
    expect(await screen.findByRole("heading", { name: "Samples", level: 2 })).toBeInTheDocument();
  });

  it("opens the palette on Ctrl-K and navigates from it", async () => {
    renderShell(staffUser({ roles: [role("reviewer")] }));
    await screen.findByRole("link", { name: "Samples" });

    await userEvent.keyboard("{Control>}k{/Control}");
    const input = await screen.findByRole("combobox", { name: "Go to" });

    await userEvent.type(input, "revi");
    // "Review Queue" survives the filter; "Samples" does not.
    expect(screen.getByRole("option", { name: "Review Queue" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Samples" })).not.toBeInTheDocument();

    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("combobox")).not.toBeInTheDocument());
  });

  it("closes the palette on Escape", async () => {
    renderShell();
    await screen.findByRole("link", { name: "Samples" });

    await userEvent.keyboard("{Control>}k{/Control}");
    expect(await screen.findByRole("combobox", { name: "Go to" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("combobox")).not.toBeInTheDocument());
  });

  it("says so rather than showing an empty list when nothing matches", async () => {
    renderShell();
    await screen.findByRole("link", { name: "Samples" });

    await userEvent.keyboard("{Control>}k{/Control}");
    await userEvent.type(await screen.findByRole("combobox", { name: "Go to" }), "zzzz");

    expect(screen.getByText(/nothing here matches/i)).toBeInTheDocument();
  });
});
