# auth/

**Owner:** DB team. **Status: stub.**

Authentication and **server-side** role enforcement for six roles: `employee`, `ap_clerk`, `approver`,
`finance_manager`, `controller_admin`, `auditor` (users come from `users.csv`).

## To provide
- `current_user` FastAPI dependency (a simple demo login or user switcher is fine: pick a user from users.csv).
- `require_role(*roles)` dependency → 403 when the role isn't allowed. Use it on **every** route.
- Terminated users (`status=terminated`) can't log in or act.
- Pass the acting user to `log_event()` so every audit row has an actor and role (and `on_behalf_of` for delegates).

The usage pattern is in `app/api/README.md`.
