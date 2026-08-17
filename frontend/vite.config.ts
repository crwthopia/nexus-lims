// defineConfig from vitest/config, not vite: the `test` block below is
// Vitest's, and vite's own UserConfig type rejects it (TS2769).
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Staff Console dev server. Everything the browser talks to goes through
// this same origin (port 5174) -- /api, /oauth2, /admin, /static are all
// proxied server-side to the Django dev server on 8000, so the browser
// never makes a genuinely cross-origin request and the Django session
// cookie "just works" with no CORS configuration needed. See
// backend/config/settings.py STAFF_CONSOLE_BASE_URL and
// apps/accounts/views.py StaffLoginCompleteView for the one place this
// single-origin assumption doesn't hold (the Entra ID OAuth2 callback,
// which Azure sends the browser to directly on port 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
  test: {
    // jsdom, not the default node environment: every test here renders real
    // components, and ProtectedRoute/AuthContext depend on document.cookie
    // and history for the redirect assertions.
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
