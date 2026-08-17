/**
 * Customer login, including the MFA step-up.
 *
 * The step-up is the interesting part and it is entirely client-side state:
 * the server answers a first-factor-only login with 400 +
 * code "MFARequiredError" (apps/accounts/customer_auth.py), and the form has
 * to read that code, reveal a second field, and retry the *same* endpoint
 * with mfa_code added. Nothing about that is visible to the backend suite,
 * which tests the endpoint's two responses independently.
 *
 * The failure mode if the code check breaks is the worst kind: a customer
 * with MFA enabled sees a generic error and can never log in, while every
 * customer without MFA is unaffected -- so it survives casual testing.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Login } from "./Login";
import { UNAUTHENTICATED, customerUser, renderWithProviders, stubApi } from "../test/helpers";

const MFA_REQUIRED = {
  status: 400,
  body: { detail: "An authenticator code is required.", code: "MFARequiredError" },
};

async function fillCredentials() {
  await userEvent.type(screen.getByLabelText(/Email/), "client@example.test");
  await userEvent.type(screen.getByLabelText(/^Password/), "correct-horse");
}

describe("first-factor login", () => {
  it("posts email and password, omitting mfa_code when the field is empty", async () => {
    const { calls } = stubApi({
      ...UNAUTHENTICATED,
      "POST /auth/customer/login": { body: customerUser() },
    });

    renderWithProviders(<Login />, { route: "/login", path: "/login" });
    await screen.findByRole("button", { name: "Log in" });
    await fillCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.method === "POST" && c.url.includes("/auth/customer/login"));
      expect(c).toBeTruthy();
      return c!;
    });
    // mfa_code must be absent, not an empty string: the serializer treats ""
    // as a supplied-but-wrong code rather than "not supplied".
    expect(post.body).toEqual({ email: "client@example.test", password: "correct-horse" });
  });

  it("shows the server's own message for bad credentials", async () => {
    stubApi({
      ...UNAUTHENTICATED,
      "POST /auth/customer/login": {
        status: 400,
        body: { detail: "Invalid email or password.", code: "InvalidCredentialsError" },
      },
    });

    renderWithProviders(<Login />, { route: "/login", path: "/login" });
    await fillCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    // Deliberately generic server-side (it must not reveal whether the email
    // exists) -- the portal's job is to pass it through unchanged.
    expect(await screen.findByText("Invalid email or password.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Authenticator code/)).not.toBeInTheDocument();
  });

  it("does not reveal the authenticator field before the server asks for it", async () => {
    stubApi(UNAUTHENTICATED);

    renderWithProviders(<Login />, { route: "/login", path: "/login" });
    await screen.findByRole("button", { name: "Log in" });

    expect(screen.queryByLabelText(/Authenticator code/)).not.toBeInTheDocument();
  });
});

describe("MFA step-up", () => {
  it("reveals the authenticator field when the server answers MFARequiredError", async () => {
    stubApi({ ...UNAUTHENTICATED, "POST /auth/customer/login": MFA_REQUIRED });

    renderWithProviders(<Login />, { route: "/login", path: "/login" });
    await fillCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByLabelText(/Authenticator code/)).toBeInTheDocument();
  });

  it("retries the same endpoint with mfa_code once the code is entered", async () => {
    let attempt = 0;
    const { calls } = stubApi({ ...UNAUTHENTICATED, "POST /auth/customer/login": MFA_REQUIRED });
    // First attempt is refused for MFA, second succeeds -- the ordering the
    // real endpoint produces.
    const original = globalThis.fetch;
    globalThis.fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
      if (String(input).includes("/auth/customer/login")) {
        attempt += 1;
        calls.push({ method: "POST", url: String(input), body: init.body ? JSON.parse(String(init.body)) : undefined });
        if (attempt === 1) {
          return new Response(JSON.stringify(MFA_REQUIRED.body), {
            status: 400,
            headers: { "content-type": "application/json" },
          });
        }
        return new Response(JSON.stringify(customerUser({ mfa_enabled: true })), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return original(input, init);
    }) as typeof fetch;

    renderWithProviders(<Login />, { route: "/login", path: "/login" });
    await fillCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    const codeField = await screen.findByLabelText(/Authenticator code/);
    await userEvent.type(codeField, "123456");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => expect(attempt).toBe(2));
    const second = calls.filter((c) => c.url.includes("/auth/customer/login")).at(-1);
    expect(second?.body).toEqual({
      email: "client@example.test",
      password: "correct-horse",
      mfa_code: "123456",
    });
  });

  it("keeps the authenticator field visible when the code itself is wrong", async () => {
    stubApi({
      ...UNAUTHENTICATED,
      "POST /auth/customer/login": MFA_REQUIRED,
    });

    renderWithProviders(<Login />, { route: "/login", path: "/login" });
    await fillCredentials();
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    await screen.findByLabelText(/Authenticator code/);

    // Retrying with a wrong code must not collapse the field and strand the
    // customer back at the first factor.
    await userEvent.type(screen.getByLabelText(/Authenticator code/), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByLabelText(/Authenticator code/)).toBeInTheDocument();
  });
});

describe("already authenticated", () => {
  it("redirects away from the login form", async () => {
    stubApi({ "/auth/customer/me": { body: customerUser() } });

    renderWithProviders(<Login />, { route: "/login", path: "/login" });

    // <Navigate to="/" /> -- assert the destination actually rendered, not
    // merely that the form is gone: a component that threw would also satisfy
    // an absence-only check.
    expect(await screen.findByText("Home page")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log in" })).not.toBeInTheDocument();
  });
});
