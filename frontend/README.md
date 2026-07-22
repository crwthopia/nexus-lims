# NASAT LIMS — Staff Console

React + TypeScript + Vite frontend for the NASAT LIMS Staff Console
(Blueprint Section 2.1 item 1). See the repo root [`README.md`](../README.md#staff-console-react-frontend)
for the full picture — architecture decisions, the login-flow port hop,
CSRF setup, and what's verified live vs. not yet built.

## Running it

```bash
npm install
npm run dev
```

Requires the Django backend running on `:8000` (`../backend`) — this dev
server proxies `/api`, `/admin`, and `/static` to it (`vite.config.ts`), so
open `http://localhost:5174`, not `:8000`, once both are running.
