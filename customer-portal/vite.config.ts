// defineConfig from vitest/config, not vite: the `test` block below is
// Vitest's, and vite's own UserConfig type rejects it (TS2769).
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Customer Portal dev server. Runs on :5173 (CUSTOMER_PORTAL_BASE_URL's
// default in backend/config/settings.py -- also the target of the
// verification-email link customer_auth.send_verification_email builds).
// Proxies /api to Django on :8000 so the browser only ever talks to one
// origin, same reasoning as the Staff Console's vite.config.ts.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    // Same configuration as the Staff Console's, for the same reason: these
    // tests render real components against a stubbed fetch.
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
