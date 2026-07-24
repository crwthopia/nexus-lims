# NASAT Labs — Customer Portal

React + TypeScript + Vite frontend for the NASAT LIMS Customer Portal
(Blueprint Section 2.1 item 1, the second of the two segregated-identity
frontends — see [`frontend/`](../frontend) for the Staff Console). See the
repo root [`README.md`](../README.md#customer-portal-react-frontend) for the
full picture — auth architecture, MFA flow, and what's verified live vs.
not yet built.

## Running it

```bash
npm install
npm run dev
```

Requires the Django backend running on `:8000` (`../backend`) — this dev
server proxies `/api` to it (`vite.config.ts`), so open
`http://localhost:5173`, not `:8000`, once both are running.
