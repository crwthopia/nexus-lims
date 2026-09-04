/**
 * The portal's header.
 *
 * The one rule it has to keep is that the nav adapts to whether there is a
 * session, because a single Layout serves both audiences: Training is
 * browsable with no account at all (Blueprint Section 4.3), so a signed-out
 * visitor must see that link and nothing that would 403, while a customer
 * must see their own screens and a way out.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Layout } from "./Layout";
import { customerUser, renderWithProviders, stubApi, UNAUTHENTICATED } from "../test/helpers";

describe("Layout", () => {
  it("offers a visitor the public catalogue, and a way in", async () => {
    stubApi(UNAUTHENTICATED);
    renderWithProviders(<Layout />, { route: "/training", path: "/training" });

    expect(await screen.findByRole("link", { name: "Register" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Training" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Log in" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Invoices" })).not.toBeInTheDocument();
  });

  it("shows a customer their own screens and their account", async () => {
    stubApi({ "/auth/customer/me": { body: customerUser({ email: "ana.reyes@example.test" }) } });
    renderWithProviders(<Layout />, { route: "/samples", path: "/samples" });

    expect(await screen.findByRole("link", { name: /ana\.reyes@example\.test/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Invoices" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Register" })).not.toBeInTheDocument();
  });
});
