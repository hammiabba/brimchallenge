"""
Shared test fixtures.

Network is blocked for every test: any test that accidentally reaches the real LLM
(or anything else) fails loudly instead of silently costing money. The only exception
is tests marked `@pytest.mark.live`, which are opt-in (see tests/extraction/test_live_llm.py).
"""
from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture(autouse=True)
def _no_learned_codings():
    # Clerk corrections live in process memory; one test's PATCH must not change another's suggestions.
    from app.coding.history_index import forget_corrections

    forget_corrections()
    yield
    forget_corrections()


# ---------------------------------------------------------------- record / replay of real model output

FIXTURES_RAW = Path(__file__).resolve().parent / "fixtures" / "raw"
_FILE_IN_REQUEST = re.compile(r"\(file: ([^)]+)\)")


class FixtureClient:
    """Stands in for the LLM client: answers each request with what the real model returned for that file.

    The file is identified from the request text ("(file: <name>)"), so the real pipeline runs end to end,
    text layer and all; only the model call is replayed. Records each call for assertions.
    """

    def __init__(self, folder: Path = FIXTURES_RAW):
        self.folder = folder
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        from app.extraction.llm_parser import RawInvoice

        self.calls.append(kwargs)
        texts = [b.get("text", "") for b in kwargs["messages"][0]["content"] if b.get("type") == "text"]
        m = next((m for t in texts if (m := _FILE_IN_REQUEST.search(t))), None)
        if m is None:
            raise LookupError("request names no file; can't pick a fixture")
        # "x.pdf.png" is how the pipeline names a misnamed file it reads by content; its fixture is "x".
        stems = (Path(m[1]).stem, Path(Path(m[1]).stem).stem)
        path = next((p for st in stems if (p := self.folder / f"{st}.json").exists()), None)
        if path is None:
            raise LookupError(f"no recorded model output for {m[1]}")
        raw = RawInvoice.model_validate(json.loads(path.read_text(encoding="utf-8"))["raw"])
        usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=to_wire(raw), usage=usage)


def to_wire(raw):
    """What the API returns for `raw`: the same values, with "" where RawInvoice has None."""
    from app.extraction.llm_parser import WireInvoice

    def blank(v):
        if isinstance(v, dict):
            return {k: blank(x) for k, x in v.items()}
        if isinstance(v, list):
            return [blank(x) for x in v]
        return "" if v is None else v

    return WireInvoice.model_validate(blank(raw.model_dump()))


def recorded_files() -> list[str]:
    """Incoming files that have a recorded model output."""
    return sorted(json.loads(p.read_text(encoding="utf-8"))["file_name"] for p in FIXTURES_RAW.glob("*.json"))


@pytest.fixture
def fake_client_from_fixtures() -> FixtureClient:
    return FixtureClient()


def replay_extract(data: bytes, filename: str, **kwargs):
    """extract_outcome with recorded model output; a drop-in for the services' extractor in API tests."""
    from app.extraction.pipeline import extract_outcome

    kwargs.setdefault("client", FixtureClient())
    return extract_outcome(data, filename, **kwargs)
