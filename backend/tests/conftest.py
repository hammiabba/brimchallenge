"""
Shared test fixtures.

Network is blocked for every test: any test that accidentally reaches the real LLM
(or anything else) fails loudly instead of silently costing money. The only exception
is tests marked `@pytest.mark.live`, which are opt-in (see tests/extraction/test_live_llm.py).
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app.reference.csv_repository import CsvReferenceRepository

DATASET = Path(__file__).resolve().parents[2] / "dataset" / "brim_ap_dataset"
INCOMING = DATASET / "incoming_invoices"


class _NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(request):
    if request.node.get_closest_marker("live"):
        yield
        return
    real_connect = socket.socket.connect

    def guard(self, address):
        # Unix sockets are local IPC, not network.
        if self.family == getattr(socket, "AF_UNIX", None):
            return real_connect(self, address)
        raise _NetworkBlocked(f"Tests must not use the network (tried {address})")

    socket.socket.connect = guard
    yield
    socket.socket.connect = real_connect


@pytest.fixture(scope="session")
def repo() -> CsvReferenceRepository:
    return CsvReferenceRepository(DATASET)


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    # Keep the LLM cache and outputs out of the real backend/.cache during tests,
    # and make sure no real API key leaks in from a developer's .env.
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(s, "output_dir", tmp_path / "output")
    monkeypatch.setattr(s, "anthropic_api_key", None)
