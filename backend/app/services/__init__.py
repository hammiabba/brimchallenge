"""
Service layer between the HTTP routes and the database / feature modules.

Owner: API lane. Routes check the role and call one service function. Services own:
- object-level scope (scope.py): which bills a user may see; out-of-scope rows raise 404, not 403
- state transitions and the calls into controls (can_approve, can_release, run_controls)
- the audit event for every write, inside the caller's transaction
- presentation rules shared by every response: money as strings (money.py), bank masking (masking.py)
"""
