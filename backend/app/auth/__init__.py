"""
Authentication and server-side role enforcement.

Owner: API lane. Public surface:
- deps.current_user     the signed-in user, read only from the session cookie
- deps.require_role     the single role gate used on every route
- roles                 role names and the role groups the routes use
- session               cookie signing and verification
"""
