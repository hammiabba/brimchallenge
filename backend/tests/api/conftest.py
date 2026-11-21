"""
Fixtures for API tests: one seeded SQLite database per test session (migrated with Alembic, then the full dataset
seed), and TestClients signed in as a given user.

Tests share the database, so a test that writes must not depend on another test's writes, and assertions about
the audit log compare against the log as it was before the test.
The repo-wide autouse fixtures (no network, no API key, temp cache dirs) still apply.
"""
from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth import session as signed_session
from app.auth.settings import get_auth_settings
from app.config import get_settings
from app.db.database import as_write_engine, get_session, get_write_session, make_engine
from app.db.seed import migrate_to_head, seed_all
from app.db.settings import get_db_settings
from app.extraction.pipeline import ExtractionOutcome
from app.main import app
from app.services import intake as intake_service
from app.services import jobs as jobs_service

# Not a secret: a fixed key so audit fingerprints are reproducible in tests (same idea as tests/db).
TEST_AUDIT_HMAC_KEY = "test-only-audit-hmac-key-0123456789abcdef"

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


@pytest.fixture(autouse=True)
def _audit_hmac_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AUDIT_HMAC_KEY", TEST_AUDIT_HMAC_KEY)
    get_db_settings.cache_clear()
    yield
    get_db_settings.cache_clear()


def _engine_on(path: Path) -> Engine:
    return make_engine(f"sqlite:///{path}")


def fake_extract(data: bytes, filename: str, **_: object) -> ExtractionOutcome:
    """Stands in for the intake lane's extractor: tests never read files with OCR or call the LLM."""
    return ExtractionOutcome(filename, "sha256:fake", "llm_skipped", error="LLM skipped: test")


@pytest.fixture(autouse=True)
def _fast_intake(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(intake_service, "extract_outcome", fake_extract)
    monkeypatch.setattr(jobs_service, "extract_outcome", fake_extract)
    jobs_service.reset_for_tests()
    yield
    jobs_service.reset_for_tests()


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A migrated, fully seeded database file. Never used directly: tests get copies of it."""
    path: Path = tmp_path_factory.mktemp("api-template") / "ap.db"
    url = f"sqlite:///{path}"
    migrate_to_head(url)
    engine = make_engine(url)
    with Session(engine) as s:
        seed_all(s, get_settings().dataset_dir)
    with engine.connect() as conn:  # fold the WAL into the main file so a plain file copy is complete
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    engine.dispose()
    return path


def _copy(template: Path, folder: Path) -> Path:
    target = folder / "ap.db"
    shutil.copyfile(template, target)
    return target


@pytest.fixture(scope="session")
def seeded_engine(seeded_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    """The shared database for read tests. Tests that change data use `fresh_engine` instead."""
    engine = _engine_on(_copy(seeded_template, tmp_path_factory.mktemp("api-shared")))
    yield engine
    engine.dispose()


@pytest.fixture
def fresh_engine(seeded_template: Path, tmp_path: Path) -> Iterator[Engine]:
    """A private copy of the seeded database for one test, so its writes can't affect any other test."""
    engine = _engine_on(_copy(seeded_template, tmp_path))
    yield engine
    engine.dispose()


def _scoped(factory: sessionmaker[Session]):
    def _session() -> Iterator[Session]:
        s = factory()
        try:
            yield s
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
    return _session


@contextmanager
def _client_on(engine: Engine) -> Iterator[TestClient]:
    read = sessionmaker(bind=engine, expire_on_commit=False)
    write = sessionmaker(bind=as_write_engine(engine), expire_on_commit=False)
    app.dependency_overrides[get_session] = _scoped(read)
    app.dependency_overrides[get_write_session] = _scoped(write)
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_write_session, None)


@pytest.fixture
def db_factory(seeded_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=seeded_engine, expire_on_commit=False)


@pytest.fixture
def client(seeded_engine: Engine) -> Iterator[TestClient]:
    with _client_on(seeded_engine) as c:
        yield c


@pytest.fixture
def fresh_db(fresh_engine: Engine) -> sessionmaker[Session]:
    """Read sessions on this test's private database, for checking what a write did."""
    return sessionmaker(bind=fresh_engine, expire_on_commit=False)


@pytest.fixture
def fresh_client(fresh_engine: Engine) -> Iterator[TestClient]:
    with _client_on(fresh_engine) as c:
        yield c


@pytest.fixture
def act_as(fresh_client: TestClient) -> Callable[[str], TestClient]:
    """act_as("U004") signs the private-database client in as that user."""

    def _act(user_id: str) -> TestClient:
        fresh_client.cookies.clear()
        r = fresh_client.post("/auth/login", json={"user_id": user_id})
        assert r.status_code == 200, r.text
        return fresh_client

    return _act


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
