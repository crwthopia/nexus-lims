/**
 * api/client.ts: the CSRF header, the 204 case, and DRF error unwrapping.
 *
 * These are the three places where a mistake is invisible in development and
 * obvious in production. The CSRF header in particular: DRF's
 * SessionAuthentication.enforce_csrf() rejects every unsafe request without
 * it, so dropping it breaks every button in the app at once while leaving
 * all the read-only screens working perfectly.
 */

import { describe, expect, it, vi } from "vitest";
import { ApiError, apiGet, apiPatch, apiPost, describeApiError } from "./client";

function stubFetch(response: Response) {
  // Typed parameters, so `calls[n][1]` is a RequestInit rather than never --
  // an untyped vi.fn() infers a zero-length tuple and every header assertion
  // below becomes a type error.
  const mock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => Promise.resolve(response));
  vi.stubGlobal("fetch", mock);
  return mock;
}

type FetchMock = ReturnType<typeof stubFetch>;

/** The RequestInit of the most recent call, asserting fetch was called at all. */
function lastInit(mock: FetchMock): RequestInit {
  const init = mock.mock.calls.at(-1)?.[1];
  if (!init) throw new Error("fetch was not called, or was called without an init");
  return init;
}

function lastUrl(mock: FetchMock): string {
  const input = mock.mock.calls.at(-1)?.[0];
  if (input === undefined) throw new Error("fetch was not called");
  return String(input);
}

/** Awaits a rejection and returns it as an ApiError, failing if it resolves. */
async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }
  throw new Error("expected the request to reject, but it resolved");
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("CSRF token", () => {
  it("is sent on unsafe methods when the cookie is present", async () => {
    document.cookie = "csrftoken=abc123";
    const mock = stubFetch(json({ ok: true }));

    await apiPost("/samples/1/receive/");

    const headers = new Headers(lastInit(mock).headers);
    expect(headers.get("X-CSRFToken")).toBe("abc123");
  });

  it("is url-decoded, since Django percent-encodes cookie values", async () => {
    document.cookie = "csrftoken=" + encodeURIComponent("a+b/c=");
    const mock = stubFetch(json({ ok: true }));

    await apiPatch("/samples/1/", { client_reference: "x" });

    const headers = new Headers(lastInit(mock).headers);
    expect(headers.get("X-CSRFToken")).toBe("a+b/c=");
  });

  it("is not sent on GET, which DRF does not check", async () => {
    document.cookie = "csrftoken=abc123";
    const mock = stubFetch(json({ results: [] }));

    await apiGet("/samples/");

    const headers = new Headers(lastInit(mock).headers);
    expect(headers.has("X-CSRFToken")).toBe(false);
  });

  it("reads the csrftoken cookie even when other cookies precede it", async () => {
    // The regex has to survive a real cookie jar; sessionid is always there.
    document.cookie = "sessionid=zzz";
    document.cookie = "csrftoken=tok999";
    const mock = stubFetch(json({ ok: true }));

    await apiPost("/samples/1/receive/");

    const headers = new Headers(lastInit(mock).headers);
    expect(headers.get("X-CSRFToken")).toBe("tok999");
  });
});

describe("request shape", () => {
  it("sends credentials so the Django session cookie rides along", async () => {
    const mock = stubFetch(json({ results: [] }));

    await apiGet("/samples/");

    expect(lastInit(mock).credentials).toBe("include");
  });

  it("prefixes the versioned API base", async () => {
    const mock = stubFetch(json({ results: [] }));

    await apiGet("/samples/");

    expect(lastUrl(mock)).toBe("/api/v1/samples/");
  });

  it("omits a body entirely when a POST has no payload", async () => {
    const mock = stubFetch(json({ ok: true }));

    await apiPost("/samples/1/receive/");

    // FSM action endpoints take no body; sending "undefined" as a JSON
    // string would make DRF reject the request as malformed.
    expect(lastInit(mock).body).toBeUndefined();
  });
});

describe("responses", () => {
  it("resolves to undefined on 204 rather than trying to parse a body", async () => {
    stubFetch(new Response(null, { status: 204 }));

    await expect(apiPost("/auth/staff/logout")).resolves.toBeUndefined();
  });

  it("throws ApiError carrying the status and parsed body on 4xx", async () => {
    stubFetch(json({ detail: "Not found." }, 404));

    const error = await rejection(apiGet("/samples/999/"));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.body).toEqual({ detail: "Not found." });
  });

  it("handles a non-JSON error body without throwing a parse error", async () => {
    // Django's own 500 page is HTML; the client must surface it, not choke.
    stubFetch(new Response("<h1>Server Error (500)</h1>", { status: 500 }));

    const error = await rejection(apiGet("/samples/"));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
  });
});

describe("describeApiError", () => {
  it("unwraps a DRF detail message", () => {
    expect(describeApiError(new ApiError(400, { detail: "Illegal transition." }))).toBe("Illegal transition.");
  });

  it("joins field errors, which DRF returns as arrays per field", () => {
    const error = new ApiError(400, { comments: ["This field is required."], status: ["Invalid."] });

    expect(describeApiError(error)).toBe("This field is required. Invalid.");
  });

  it("passes a plain string body through", () => {
    expect(describeApiError(new ApiError(400, "Something specific went wrong."))).toBe(
      "Something specific went wrong.",
    );
  });

  it("falls back to a generic line for a non-ApiError", () => {
    // A TypeError from a dropped connection must not render as "[object
    // Object]" or leak a stack trace into the UI.
    expect(describeApiError(new TypeError("Failed to fetch"))).toBe("Something went wrong.");
    expect(describeApiError(undefined)).toBe("Something went wrong.");
  });
});
