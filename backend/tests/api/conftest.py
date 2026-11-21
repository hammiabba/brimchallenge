"""
Fixtures for API tests: one seeded SQLite database per test session (migrated with Alembic, then the full dataset
seed), and TestClients signed in as a given user.

Tests here only read, or write inside a transaction the fixture rolls back, so the shared database stays as seeded.
The repo-wide autouse fixtures (no network, no API key, temp cache dirs) still apply.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import session as signed_session
from app.auth.settings import get_auth_settings
from app.config import get_settings
from app.db.database import get_session, make_engine
from app.db.seed import migrate_to_head, seed_all
from app.main import app

# One user per role, from the seeded users.csv.
ROLE_USERS = {
    "employee": "U013",          # D01 dispatcher
    "ap_clerk": "U004",
    "approver": "U007",          # D01 manager
    "finance_manager": "U003",   # also U012's delegate (P08)
    "controller_admin": "U002",
    "auditor": "U006",
}
TERMINATED_USER = "U015"
ON_LEAVE_USER = "U012"

# Bills used for scope checks: D01 is the employee's and approver's department, D05 is not.
IN_SCOPE_BILL = "AP-00024"      # D01
OUT_OF_SCOPE_BILL = "AP-00001"  # D05


@pytest.fixture(scope="session")
def seeded_engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    path: Path = tmp_path_factory.mktemp("api-db") / "ap.db"
    url = f"sqlite:///{path}"
    migrate_to_head(url)
    engine = make_engine(url)
    with Session(engine) as s:
        seed_all(s, get_settings().dataset_dir)
    yield engine
    engine.dispose()


@pytest.fixture
def db_factory(seeded_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=seeded_engine, expire_on_commit=False)


@pytest.fixture
def client(db_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        s = db_factory()
        try:
            yield s
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def login(client: TestClient) -> Callable[[str], TestClient]:
    """login("U004") signs the shared client in as that user (replacing any earlier session)."""

    def _login(user_id: str) -> TestClient:
        client.cookies.clear()
        r = client.post("/auth/login", json={"user_id": user_id})
        assert r.status_code == 200, r.text
        return client

    return _login


@pytest.fixture
def as_role(login: Callable[[str], TestClient]) -> Callable[[str], TestClient]:
    return lambda role: login(ROLE_USERS[role])


def forge_cookie(client: TestClient, user_id: str) -> None:
    """Set a validly signed cookie for any user id, bypassing /auth/login (used to test terminated users)."""
    client.cookies.clear()
    client.cookies.set(get_auth_settings().session_cookie_name, signed_session.issue(user_id))
