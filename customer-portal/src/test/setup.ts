/**
 * Vitest setup, loaded once per test file (vite.config.ts `setupFiles`).
 *
 * jest-dom adds the DOM matchers these tests lean on (`toBeDisabled`,
 * `toBeInTheDocument`), and `cleanup` unmounts anything a test rendered.
 * Vitest with `globals: true` runs cleanup automatically, but only for the
 * testing-library instance it can see -- calling it explicitly keeps that
 * independent of the auto-detection.
 */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  // Cookies survive jsdom teardown between tests in the same file; the API
  // client reads document.cookie for the CSRF token, so a token set by one
  // test must not leak into the next.
  document.cookie.split(";").forEach((c) => {
    const name = c.split("=")[0].trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });
});
