"""Every role x every endpoint, plus 401 for every operation in the OpenAPI spec when no session is sent."""
from __future__ import annotations

import re

import pytest

from tests.api.conftest import ROLE_USERS, forge_cookie
from tests.api.matrix import CASES, Case

PUBLIC = {("GET", "/health"), ("GET", "/auth/users"), ("POST", "/auth/login")}


def _call(client, case: Case):
    return client.request(case.method, case.path, **case.kwargs)


@pytest.mark.parametrize("role", list(ROLE_USERS))
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_role_matrix(request, case: Case, role: str):
    # Reads share one database; each write cell gets its own fresh copy, so its outcome never depends on what
    # another cell changed.
    if case.method == "GET":
        client = request.getfixturevalue("as_role")(role)
    else:
        client = request.getfixturevalue("act_as")(ROLE_USERS[role])
    r = _call(client, case)
    assert r.status_code == case.expected(role), f"{role} {case.id}: {r.status_code} {r.text[:300]}"
    if r.status_code >= 400:
        assert set(r.json()["error"]) == {"code", "message", "details"}
    if r.status_code == 404:
        # Out of scope and nonexistent look identical apart from the id in the message.
        assert r.json()["error"]["code"].endswith(".not_found")


def _spec_operations(client) -> list[tuple[str, str]]:
    spec = client.get("/openapi.json").json()
    return [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops]


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "X1", path)


def test_matrix_covers_every_operation(client):
    """A new endpoint without a matrix row fails here, so nobody can add a route without deciding its roles."""
    skip = PUBLIC | {("POST", "/intake/upload"), ("POST", "/intake/inbox/run")}  # covered in test_intake_guard
    missing = []
    for method, template in _spec_operations(client):
        if (method, template) in skip:
            continue
        pattern = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", template) + "$")
        if not any(c.method == method and pattern.match(c.path) for c in CASES):
            missing.append(f"{method} {template}")
    assert not missing, f"endpoints without a permission-matrix row: {missing}"


def test_every_non_public_operation_needs_a_session(client):
    client.cookies.clear()
    failures = []
    for method, path in _spec_operations(client):
        if (method, path) in PUBLIC:
            continue
        r = client.request(method, _concrete(path))
        if r.status_code != 401:
            failures.append(f"{method} {path} -> {r.status_code}")
    assert not failures, failures


def test_terminated_user_is_rejected_everywhere(client):
    forge_cookie(client, "U015")
    for method, path in _spec_operations(client):
        if (method, path) in PUBLIC:
            continue
        assert client.request(method, _concrete(path)).status_code == 401, f"{method} {path}"
