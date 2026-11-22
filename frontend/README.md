# frontend/

The AP Automation web app: Vite + React + TypeScript (strict), Mantine, TanStack Query and React Router. It talks to
the FastAPI backend through a typed client generated from the backend's OpenAPI spec.

Every screen in the sidebar is built: intake (upload, submissions, the AP inbox), the review queue and the bill screen
with AP's actions, approvals (including delegated steps and unassigned steps), payments (dashboard, schedule,
release, cancel, payment detail), vendors and bank changes, spend, the audit log with CSV export, admin (users,
policies, absences), out of office, bank reconciliation and early payment. To run the whole app with the demo data,
see "Run the whole app" in the [root README](../README.md).

## Install

Node 20 or newer (`.nvmrc` pins the major version used, 24). From `frontend/`:

```bash
npm ci
```

## Run

1. Backend, from `backend/` with the repo's venv active, on port 8000. The database must be seeded (and, for flags
   on history bills, back-filled):
   ```bash
   python -m app.db.seed --reset && python -m app.db.backfill   # once
   uvicorn app.main:app --port 8000
   ```
2. Frontend, from `frontend/`:
   ```bash
   npm run dev
   ```
3. Open **http://localhost:5173** (not 127.0.0.1). The two are different sites to the browser: the session cookie set
   through localhost isn't sent to 127.0.0.1, and the backend's origin check accepts only the origins in
   `FRONTEND_ORIGINS` (default `http://localhost:5173`).

The dev server proxies `/api/*` to `http://127.0.0.1:8000` with the `/api` prefix stripped (`vite.config.ts`), so
API calls are same-origin and the cookie just works. Sign in by picking a person; there are no passwords.

## Scripts

| Script | What |
|---|---|
| `npm run dev` | Dev server on port 5173 with the API proxy |
| `npm run build` | Type-check (`tsc -b`) and build to `dist/` |
| `npm run preview` | Serve the built `dist/` |
| `npm run typecheck` | `tsc --noEmit` for the app and the Vite config |
| `npm run lint` | oxlint (the Vite template's linter), warnings fail |
| `npm run test` | Vitest once (jsdom; no network, fetch is stubbed) |
| `npm run gen:api` | Regenerate `openapi.json` and `src/api/schema.d.ts` from the backend |

## API types

`openapi.json` and `src/api/schema.d.ts` are generated and checked in, so the UI builds without the backend.
After an API change, regenerate them and commit both:

```bash
npm run gen:api
```

`scripts/dump-openapi.sh` imports `app.main` with the repo's `.venv` and writes the spec (sorted keys, so the output
is reproducible); no server is needed. openapi-typescript then writes the types. Import types from
`src/api/types.ts`, not from the generated file.

Calls go through the client in `src/api/client.ts`:

```ts
const me = await unwrap(api.GET('/auth/me'))
```

`unwrap` returns the data or throws an `ApiError` (`status`, `code`, `message`, `details`, `request_id`) read from
the API's error envelope `{"error": {"code", "message", "details"}, "request_id"}`. A 401 from any call (except the
sign-in itself) signs the user out and shows the login page. 403, 404, 409, 422 and 501 are thrown for the screen to
handle; `notifyError(error)` shows one as a notification with the request id in small text, and `<ErrorAlert>` shows
one inline.

## Layout

```
src/
  api/      client, ApiError, generated schema, notifications, query client defaults, reference-data hooks
  auth/     AuthProvider (GET /auth/me), LoginPage, RequireAuth, role labels
  shell/    AppLayout (header, sidebar, delegate banner), navigation.ts, placeholder and 404 pages
  intake/   submit an invoice, my submissions, the AP inbox run and email detail
  bills/    bills list and review queue (filters in the URL), the bill detail with its actions, evidence renderers
  approvals/ my approvals, unassigned steps
  payments/ payments dashboard, schedule / release / cancel, payment detail
  vendors/  vendor list and page, onboarding, bank change requests (and roles.ts: who sees which vendor button)
  bankChanges/ the bank change queue (verify, reject)
  reconciliation/ bank reconciliation; earlyPay/ early payment
  spend/, audit/, admin/, delegation/  spend report, audit log, users / policies / absences, out of office
  lib/      money.ts, dates.ts, decimal.ts (with tests)
  ui/       shared pieces: badges, Id / MoneyText / DateText, Icon, contrast check
  styles/   self-hosted fonts and the few global CSS rules
  test/     test setup, fake API, fixtures, render helper
  theme.ts  colours (Brim palette), type scale and Mantine component defaults
  config.ts APP_NAME
```

The sidebar for each role is one config file, `src/shell/navigation.ts`. To add a screen, add an item there, list it
under the roles that use it, and add its lazy-loaded component to `SCREENS` in `App.tsx` (screens load as their own
bundle chunks on first visit).

Buttons follow the server. A bill or payment answer carries `allowed_actions` (what the signed-in user may do now,
with the reason when not); a button is shown only when it is allowed, and a refusal on submit shows the server's
message and request id. Answers without `allowed_actions` (vendors, bank changes) use the API's role gates, kept in
one place per area (for example `src/vendors/roles.ts`). The server checks every request either way. Lists keep
their filters and page in the URL (`?status=needs_review&vendor=V011&department=D01&q=000804&page=2`).

## Design

[`DESIGN.md`](DESIGN.md) is the source of design rules for every chunk: colours and their contrast, type, layout,
tables, icons, motion, copy and the "Never" list. Fonts (IBM Plex) are self-hosted through Fontsource; icons are
Tabler only, through `<Icon>`. `src/ui/contrast.test.ts` checks every colour pair in the theme and
`src/design.test.ts` checks the sources against the "Never" list.

## Rules

**Money is a string, never a number.** The API sends amounts as `"742.30"` and accepts only strings. Never use
`Number()`, `parseFloat`, unary `+` or arithmetic on a money value. Use `src/lib/money.ts`:
- `formatMoney(m, currency)` for display. Convention: CAD shows a plain `$` (`$1,000.00`); USD is always `US$1,000.00`;
  other currencies show their code (`EUR 1,000.00`); negatives are `-$50.00`.
- `toCents` / `fromCents` / `sumMoney` (BigInt cents) for the rare sum.
- `parseMoneyInput` for form input: the API's own pattern `^-?\d{1,12}(\.\d{1,2})?$`, padded to two decimals.

**Dates.** A date-only value (`"2026-11-02"`) is a calendar date: format it with `formatDate` (string splitting).
Never `new Date("2026-11-02")`: that is midnight UTC, the previous evening in Canada. Timestamps arrive in UTC with
`Z`; `formatTimestamp` shows them in the browser's time zone (and warns once if one arrives without an offset). The
tests run in America/Toronto so the previous-day bug can't come back unnoticed.

**Security is the server's job.** The UI hides what a role can't use, but hiding is never the security. The server
checks the session and the role on every request, scopes data by department (404 outside your scope) and enforces
the approval and payment rules. Every route exists for every signed-in user; the navigation only decides what to show.
The session cookie is httpOnly: no JavaScript reads it.

**No emojis** in code or UI text, and comments on every non-trivial function and component.
