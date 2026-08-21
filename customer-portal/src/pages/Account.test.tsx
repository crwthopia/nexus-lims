/**
 * Account: TOTP MFA enrollment.
 *
 * A three-state flow, and the states matter. The secret is only issued by
 * `enable`, and `mfa_enabled` only flips once the customer proves they can
 * generate a code from it — so a screen that showed "MFA is enabled" after
 * the enable call, without waiting for confirmation, would lock a customer
 * out of their own account at next login with a secret they never
 * successfully stored.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Account } from "./Account";
import { customerUser, renderWithProviders, stubApi } from "../test/helpers";

const PROVISIONING = {
  secret: "JBSWY3DPEHPK3PXP",
  provisioning_uri: "otpauth://totp/NexusLIMS:client@example.test?secret=JBSWY3DPEHPK3PXP",
};

function render(user = customerUser(), extra = {}) {
  const stub = stubApi({
    "/auth/customer/me": { body: user },
    ...extra,
  });
  renderWithProviders(<Account />, { route: "/account", path: "/account" });
  return stub;
}

describe("the profile", () => {
  it("shows the account's own details", async () => {
    render(customerUser({ organization_name: "Example Manufacturing" }));

    expect(await screen.findByText("client@example.test")).toBeInTheDocument();
    expect(screen.getByText("Example Manufacturing")).toBeInTheDocument();
  });

  it("shows an em dash for details the customer has not supplied", async () => {
    render(customerUser({ organization_name: null, prc_license_number: null }));
    await screen.findByText("client@example.test");

    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("reports whether the email has been verified", async () => {
    render(customerUser({ is_email_verified: false }));
    await screen.findByText("client@example.test");

    expect(screen.getByText("No")).toBeInTheDocument();
  });
});

describe("before enrollment", () => {
  it("offers to enable MFA", async () => {
    render();

    expect(await screen.findByRole("button", { name: "Enable MFA" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Authenticator code")).not.toBeInTheDocument();
  });

  it("does not reveal a secret until one has been requested", async () => {
    // The secret is issued by the enable call. Rendering one before that
    // would mean the client invented it.
    render();
    await screen.findByRole("button", { name: "Enable MFA" });

    expect(screen.queryByText(PROVISIONING.secret)).not.toBeInTheDocument();
  });

  it("surfaces a failure to start enrollment", async () => {
    render(customerUser(), {
      "POST /auth/customer/mfa/enable": { status: 400, body: { detail: "MFA is already enrolled." } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Enable MFA" }));

    expect(await screen.findByText("MFA is already enrolled.")).toBeInTheDocument();
  });
});

describe("mid-enrollment", () => {
  async function startEnrollment(extra = {}) {
    const stub = render(customerUser(), {
      "POST /auth/customer/mfa/enable": { body: PROVISIONING },
      ...extra,
    });
    await userEvent.click(await screen.findByRole("button", { name: "Enable MFA" }));
    await screen.findByLabelText("Authenticator code");
    return stub;
  }

  it("shows the secret so it can be added to an authenticator app", async () => {
    await startEnrollment();

    expect(screen.getByText(PROVISIONING.secret)).toBeInTheDocument();
  });

  it("does not claim MFA is enabled before the code is confirmed", async () => {
    // The whole point of the confirm step: the server has issued a secret
    // but mfa_enabled is still false, and saying otherwise would leave a
    // customer locked out at next login.
    await startEnrollment();

    expect(screen.queryByText("MFA is enabled on your account.")).not.toBeInTheDocument();
  });

  it("sends the entered code to confirm", async () => {
    const { calls } = await startEnrollment({
      "POST /auth/customer/mfa/confirm": { body: customerUser({ mfa_enabled: true }) },
    });

    await userEvent.type(screen.getByLabelText("Authenticator code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    const post = await waitFor(() => {
      const c = calls.find((c) => c.url.includes("/mfa/confirm"));
      expect(c).toBeTruthy();
      return c!;
    });
    expect(post.body).toEqual({ code: "123456" });
  });

  it("re-reads the account after confirming rather than assuming success", async () => {
    // mfa_enabled is the server's to report. Setting it locally would show
    // "enabled" even if the confirm silently did not take.
    const { calls } = await startEnrollment({
      "POST /auth/customer/mfa/confirm": { body: customerUser({ mfa_enabled: true }) },
    });
    const readsBefore = calls.filter((c) => c.method === "GET" && c.url.includes("/auth/customer/me")).length;

    await userEvent.type(screen.getByLabelText("Authenticator code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      const readsAfter = calls.filter((c) => c.method === "GET" && c.url.includes("/auth/customer/me")).length;
      expect(readsAfter).toBeGreaterThan(readsBefore);
    });
  });

  it("keeps the code field up when the code is wrong", async () => {
    // Retrying is the expected path — clocks drift, codes expire. Collapsing
    // back to "Enable MFA" would discard the secret the customer has already
    // stored in their authenticator app.
    await startEnrollment({
      "POST /auth/customer/mfa/confirm": { status: 400, body: { detail: "That code is not valid." } },
    });

    await userEvent.type(screen.getByLabelText("Authenticator code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("That code is not valid.")).toBeInTheDocument();
    expect(screen.getByLabelText("Authenticator code")).toBeInTheDocument();
    expect(screen.getByText(PROVISIONING.secret)).toBeInTheDocument();
  });
});

describe("after enrollment", () => {
  it("says MFA is enabled and offers no way to re-enrol", async () => {
    // Re-enrolling would issue a new secret and invalidate the one the
    // customer is using.
    render(customerUser({ mfa_enabled: true }));

    expect(await screen.findByText("MFA is enabled on your account.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enable MFA" })).not.toBeInTheDocument();
  });
});
