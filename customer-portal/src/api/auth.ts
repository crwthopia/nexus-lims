import { apiGet, apiPost } from "./client";
import type { CustomerMe } from "./types";

export function registerCustomer(data: { email: string; password: string; organization_name?: string; prc_license_number?: string }) {
  return apiPost<CustomerMe>("/auth/customer/register", data);
}

export function verifyEmail(token: string) {
  return apiPost<CustomerMe>("/auth/customer/verify-email", { token });
}

/** code and message mirror apps/accounts/customer_auth.py's exception class names (InvalidCredentialsError, EmailNotVerifiedError, MFARequiredError, InvalidMFACodeError). */
export interface CustomerAuthErrorBody {
  detail: string;
  code: string;
}

export function loginCustomer(data: { email: string; password: string; mfa_code?: string }) {
  return apiPost<CustomerMe>("/auth/customer/login", data);
}

export function logoutCustomer() {
  return apiPost<void>("/auth/customer/logout");
}

export function getMe() {
  return apiGet<CustomerMe>("/auth/customer/me");
}

export function enableMfa() {
  return apiPost<{ secret: string; provisioning_uri: string }>("/auth/customer/mfa/enable");
}

export function confirmMfa(code: string) {
  return apiPost<CustomerMe>("/auth/customer/mfa/confirm", { code });
}
