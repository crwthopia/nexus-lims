/**
 * Fetch wrapper for the DRF API. Talks to /api/v1 (proxied by Vite's dev
 * server to the Django backend on 8000, see vite.config.ts), so requests
 * are always same-origin as far as the browser is concerned -- no CORS
 * setup needed, and the Django session cookie is sent automatically.
 *
 * DRF's SessionAuthentication.enforce_csrf() requires an X-CSRFToken header
 * matching the csrftoken cookie on any unsafe method (POST/PATCH/etc.),
 * exactly like Django's own CsrfViewMiddleware -- readCsrfToken() below
 * reads the cookie Django's CSRF machinery already sets on any response
 * once a session exists.
 */

const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(typeof body === "string" ? body : JSON.stringify(body));
    this.status = status;
    this.body = body;
  }
}

function readCsrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);

  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
    const csrfToken = readCsrfToken();
    if (csrfToken) headers.set("X-CSRFToken", csrfToken);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    throw new ApiError(response.status, body);
  }
  return body as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path);
}

export function apiPost<T>(path: string, data?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: data !== undefined ? JSON.stringify(data) : undefined });
}

/** Turns a DRF error response body (field-error dict, {"detail": ...}, or a plain string) into one displayable line. */
export function describeApiError(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong.";
  if (typeof error.body === "string") return error.body;
  if (error.body && typeof error.body === "object") {
    const values = Object.values(error.body as Record<string, unknown>).flat();
    if (values.length) return values.join(" ");
  }
  return error.message;
}
