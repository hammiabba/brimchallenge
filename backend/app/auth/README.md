# auth/

**Owner:** the API module. **Status:** demo sign-in, signed session cookie, role gate.

Authentication and **server-side** role enforcement for six roles: `employee`, `ap_clerk`, `approver`,
`finance_manager`, `controller_admin`, `auditor` (users come from the `users` table, seeded from users.csv).

## Files
| File | What |
|---|---|
| `deps.py` | `current_user` (identity from the session cookie only; user row re-read every request; unknown or terminated users get 401) and `require_role(*roles)` (403 if the role isn't listed). Also `CurrentUser`, `active_delegations`. |
| `session.py` | `issue(user_id)` / `verify(token)`: HMAC-SHA256 signed cookie, stdlib only. Holds user id, issue time, expiry, session id; no role. |
| `settings.py` | `AuthSettings` read from env / `.env`: `SESSION_SECRET`, `SESSION_TTL_HOURS` (8), `COOKIE_SECURE` (auto), `FRONTEND_ORIGINS` (`http://localhost:5173`), `MAX_BODY_BYTES` (10 MB). Kept out of `app/config.py`. |
| `roles.py` | Role names and the groups routes use (`SIGNERS`, `RELEASERS`, `FULL_BANK_DETAILS`, ...). |

## Rules
- Identity comes **only** from the signed cookie. No route reads a user id from a header or body (except `POST /auth/login`, which is the demo sign-in).
- Every route except `/health`, `GET /auth/users` and `POST /auth/login` depends on `current_user` (directly or through `require_role`). `tests/api/test_permission_matrix.py` fails if any operation in the OpenAPI spec answers without a session.
- Role checks live only in `require_role`. Object rules (department scope, P07 self-approval, P11 separation of duties, limits) live in `app/services` and `app/controls`.
- On-leave users can sign in; controls refuse them as approvers (`can_approve` requires `active`). Their delegate sees them in `/auth/me` → `acting_for`.
- Cookie: `HttpOnly`, `SameSite=Lax`, `Secure` unless every frontend origin is plain-http localhost. Use `http://localhost:5173`, not `127.0.0.1`, or the browser won't send it.
- Stateless sessions: logout clears the cookie but can't revoke a copy before it expires (8 h). Revocation would need a sessions table.

Set `SESSION_SECRET` in `.env` for a stable demo; without it a random secret is generated at startup and sessions end on restart.
