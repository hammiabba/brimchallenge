"""
Audit log: write events into the hash chain, verify the chain, and read events for the audit API.

Owner: DB team.

How the chain works:
- Every event stores prev_hash (the hash of the event before it; "GENESIS" for the first one) and its own hash:
  sha256(prev_hash + "\\n" + canonical JSON of the event's fields). Changing, inserting or deleting a row in the middle
  breaks every hash after it, and verify_chain() finds the first broken row.
- A UNIQUE index on prev_hash (migration 0002) means two events can never extend the same predecessor, so the chain
  can't fork. log_event() retries when it loses that race.
- Triggers from migration 0001 block UPDATE and DELETE on audit_events altogether.

Transactions: log_event() never commits, rolls back the caller's work, or closes the session. It inserts inside a
SAVEPOINT in the caller's transaction, so the event and the state change it describes commit (or roll back) together.
On SQLite it must be given a write session (app.db.database.get_write_session: BEGIN IMMEDIATE), so the write lock is
held from before the latest hash is read until the caller commits; a read session raises RuntimeError.

Authorization is the caller's job. The read helpers return whatever matches the filters.

Bank account numbers never enter the log:
- before/after values under account-number keys become {"last4", "fingerprint"}, where the fingerprint is
  HMAC-SHA256 keyed by AUDIT_HMAC_KEY (app.db.settings), so two events about one account can still be matched but a
  number can't be recovered by hashing every possible account.
- runs of 7+ digits are masked to their last 4 in `comment`, and in before/after text under keys containing
  "comment", "note" or "memo" (free text where someone might paste an account number).
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import math
import re
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import SQLITE_BEGIN_OPTION
from app.db.settings import get_db_settings
from app.db.types import dec_to_text, to_utc, utcnow
from app.shared import schemas

# ---------------------------------------------------------------- constants

SYSTEM_ACTOR = "system"  # actor_user_id (and actor_role) for the seed and background jobs
GENESIS = "GENESIS"  # prev_hash of the first event in the chain
MAX_ATTEMPTS = 5  # log_event tries this many times when another writer took the same prev_hash
PREV_HASH_INDEX = "uq_audit_events_prev_hash"
MAX_PAGE = 500  # largest page list_events returns
CSV_BATCH = 500  # rows fetched per query while streaming the CSV export

# Keys whose values are full bank account numbers and must never be stored as-is.
ACCOUNT_KEYS = frozenset({"account", "new_account", "bank_account", "account_number"})
# Payload keys holding free text (matched case-insensitively as substrings): their digit runs are masked.
TEXT_KEY_WORDS = ("comment", "note", "memo")
MIN_HMAC_KEY_LENGTH = 32  # characters of AUDIT_HMAC_KEY
WRITE_SESSION_REQUIRED = "log_event requires a write session (get_write_session)"
_DIGIT_RUN = re.compile(r"[0-9]{7,}")  # ASCII digits only, so the masking is predictable

_table = models.AuditEvent.__table__


class AuditAction:
    """Standard action names (dotted: <entity>.<verb>). log_event accepts any string; these keep names consistent."""

    BILL_CREATED = "bill.created"
    BILL_UPDATED = "bill.updated"
    BILL_CODING_CHANGED = "bill.coding_changed"
    BILL_FLAG_OVERRIDDEN = "bill.flag_overridden"
    BILL_FLAG_RESOLVED = "bill.flag_resolved"
    BILL_SUBMITTED = "bill.submitted"
    BILL_APPROVED = "bill.approved"
    BILL_REJECTED = "bill.rejected"
    BILL_VOIDED = "bill.voided"
    PAYMENT_SCHEDULED = "payment.scheduled"
    PAYMENT_RELEASED = "payment.released"
    PAYMENT_CANCELLED = "payment.cancelled"
    VENDOR_CREATED = "vendor.created"
    VENDOR_APPROVED = "vendor.approved"
    VENDOR_STATUS_CHANGED = "vendor.status_changed"
    VENDOR_BANK_CHANGE_REQUESTED = "vendor.bank_change_requested"
    VENDOR_BANK_CHANGE_VERIFIED = "vendor.bank_change_verified"
    VENDOR_BANK_CHANGE_REJECTED = "vendor.bank_change_rejected"
    POLICY_UPDATED = "policy.updated"
    ABSENCE_CREATED = "absence.created"
    ABSENCE_ENDED = "absence.ended"
    USER_UPDATED = "user.updated"
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    INTAKE_ITEM_CREATED = "intake.item_created"
    INTAKE_RUN_STARTED = "intake.run_started"
    INTAKE_RUN_FINISHED = "intake.run_finished"
    AUDIT_EXPORTED = "audit.exported"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        """Every standard action name, in declaration order."""
        return tuple(v for k, v in vars(cls).items() if k.isupper() and isinstance(v, str))


class AuditChainConflict(RuntimeError):
    """log_event lost the prev_hash race MAX_ATTEMPTS times in a row; nothing was written."""


class AuditKeyError(RuntimeError):
    """AUDIT_HMAC_KEY is missing or too short, so bank account fingerprints can't be computed. Never shows the key."""


class AuditRecord(schemas.AuditEvent):
    """A stored audit event: the shared schemas.AuditEvent plus the columns the API needs to page and verify.

    seq is required for keyset pagination (list_events(after_seq=...)). It's a subclass, not a parallel model:
    anything that accepts a schemas.AuditEvent accepts an AuditRecord. `at` is timezone-aware UTC.
    """

    seq: int
    request_id: str | None = None
    prev_hash: str | None = None
    hash: str


@dataclass(frozen=True)
class ChainReport:
    """Result of verify_chain: ok, how many events were checked, and the first bad one (if any) and why."""

    ok: bool
    count: int
    first_bad_seq: int | None = None
    reason: str | None = None


# ---------------------------------------------------------------- JSON for the log


def _iso_utc(value: datetime) -> str:
    """A datetime as ISO 8601 in UTC with a trailing Z. Naive values are taken to be UTC (the storage convention)."""
    return to_utc(value).isoformat() + "Z"


def to_audit_json(value: Any) -> Any:
    """Convert a value into plain JSON types, deterministically, for storing and hashing.

    Decimal -> exact string (never float); datetime -> ISO 8601 UTC with "Z"; date -> ISO date; Enum -> its value;
    pydantic model -> model_dump(mode="json"); set -> sorted list; tuple -> list; dict keys must be str (int and Enum
    keys are converted). Finite floats pass through (e.g. confidence scores); NaN/infinity raise ValueError.
    Anything else raises TypeError, so an unexpected object can never be stored as an opaque repr.
    """
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"not a finite number: {value!r}")
        return value
    if isinstance(value, Decimal):
        return dec_to_text(value)  # exact digits, no exponent notation; refuses NaN / infinity
    if isinstance(value, datetime):  # before date: datetime is a subclass of date
        return _iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_audit_json(value.value)
    if isinstance(value, BaseModel):
        return to_audit_json(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if isinstance(key, Enum):
                key = key.value
            if isinstance(key, int) and not isinstance(key, bool):
                key = str(key)
            if not isinstance(key, str):
                raise TypeError(f"audit JSON keys must be strings, got {type(key).__name__}")
            out[key] = to_audit_json(item)
        return out
    if isinstance(value, list | tuple):
        return [to_audit_json(item) for item in value]
    if isinstance(value, set | frozenset):
        items = [to_audit_json(item) for item in value]
        # Sort by canonical JSON text, which works even when the members have different types.
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    raise TypeError(f"cannot store {type(value).__name__} in the audit log")


def _hmac_key() -> bytes:
    """AUDIT_HMAC_KEY as bytes. Raises AuditKeyError (which never includes the key) if it's missing or too short."""
    secret = get_db_settings().AUDIT_HMAC_KEY
    key = secret.get_secret_value() if secret is not None else ""
    if len(key) < MIN_HMAC_KEY_LENGTH:
        raise AuditKeyError(
            f"AUDIT_HMAC_KEY is missing or shorter than {MIN_HMAC_KEY_LENGTH} characters, so bank account numbers "
            "can't be fingerprinted for the audit log. Set it in .env to 32+ random characters, e.g. "
            "python -c \"import secrets; print(secrets.token_hex(32))\"")
    return key.encode("utf-8")


def _fingerprint(account: str) -> str:
    """First 12 hex characters of HMAC-SHA256(AUDIT_HMAC_KEY, account).

    Matches two mentions of one account without storing it. Keyed, so the number can't be recovered by hashing every
    possible 7-12 digit account (an unsalted sha256 of a short number can be brute-forced).
    """
    return hmac.new(_hmac_key(), account.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def mask_digit_runs(text: str) -> str:
    """Mask every run of 7+ digits to stars plus its last 4: "acct 593014216" -> "acct *****4216".

    Shorter numbers (invoice numbers, amounts, dates written with separators) are left as they are.
    """
    return _DIGIT_RUN.sub(lambda m: "*" * (len(m.group()) - 4) + m.group()[-4:], text)


def _is_text_key(key: str) -> bool:
    """True for payload keys holding free text ("comment", "internal_notes", "memo", ...)."""
    lowered = key.lower()
    return any(word in lowered for word in TEXT_KEY_WORDS)


def _redact(value: Any, in_text: bool) -> Any:
    """redact() worker. `in_text` is True inside a free-text key's subtree, where strings get their digits masked."""
    if isinstance(value, str):
        return mask_digit_runs(value) if in_text else value
    if isinstance(value, list):
        return [_redact(item, in_text) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key in ACCOUNT_KEYS and isinstance(item, str | int) and not isinstance(item, bool) and str(item).strip():
            number = str(item).strip()
            out[key] = {"last4": number[-4:], "fingerprint": _fingerprint(number)}
        else:
            out[key] = _redact(item, in_text or _is_text_key(key))
    return out


def redact(value: Any) -> Any:
    """Remove bank account numbers from a JSON-safe payload, recursively.

    - Values under the keys in ACCOUNT_KEYS become {"last4", "fingerprint"} (HMAC; needs AUDIT_HMAC_KEY).
    - Strings under keys containing "comment", "note" or "memo" get runs of 7+ digits masked to their last 4.
    institution, transit and *_last4 keys are left alone, and so is anything already redacted (a dict) or empty.
    Apply it to payloads (before / after), never to IDs.
    """
    return _redact(value, in_text=False)


# ---------------------------------------------------------------- hashing


def canonical_bytes(fields: Mapping[str, Any]) -> bytes:
    """Deterministic JSON encoding of an event's fields (everything except seq and hash): sorted keys, no spaces."""
    trimmed = {k: v for k, v in fields.items() if k not in ("seq", "hash")}
    return json.dumps(trimmed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_hash(prev_hash: str, fields: Mapping[str, Any]) -> str:
    """sha256 hex of prev_hash, a newline, and the event's canonical bytes."""
    return hashlib.sha256(prev_hash.encode("utf-8") + b"\n" + canonical_bytes(fields)).hexdigest()


def _hash_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """The fields that go into an event's hash, from a row (or a row about to be inserted).

    `at` is rendered as an ISO string so the same instant always hashes the same, whether it comes from Python or
    back from SQLite.
    """
    return {
        "event_id": row["event_id"],
        "at": _iso_utc(row["at"]),
        "actor_user_id": row["actor_user_id"],
        "actor_role": row["actor_role"],
        "on_behalf_of": row["on_behalf_of"],
        "action": row["action"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "before_json": row["before_json"],
        "after_json": row["after_json"],
        "comment": row["comment"],
        "request_id": row["request_id"],
        "prev_hash": row["prev_hash"],
    }


# ---------------------------------------------------------------- writing


def _require_write_session(session: Session) -> None:
    """On SQLite, refuse to log unless the session is a write session (its transaction began with BEGIN IMMEDIATE).

    A write session holds SQLite's write lock from its first statement, so nobody can append to the chain between
    log_event reading the latest hash and inserting the new event. Fetching the connection starts the session's
    transaction (via the engine's begin listener) if it hasn't started yet. Other databases are not checked.
    """
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    if connection.get_execution_options().get(SQLITE_BEGIN_OPTION) != "IMMEDIATE":
        raise RuntimeError(WRITE_SESSION_REQUIRED)


def _latest_hash(session: Session) -> str:
    """Hash of the event with the highest seq, as this transaction sees it; GENESIS when the log is empty."""
    latest = session.execute(select(_table.c.hash).order_by(_table.c.seq.desc()).limit(1)).scalar()
    return latest if latest is not None else GENESIS


def _is_prev_hash_conflict(exc: IntegrityError) -> bool:
    """True when the IntegrityError is the prev_hash unique index (another writer extended the same event)."""
    message = str(exc.orig)
    return "audit_events.prev_hash" in message or PREV_HASH_INDEX in message


def _record(row: Mapping[str, Any]) -> AuditRecord:
    """A stored row (or the values just inserted) as an AuditRecord, with `at` as aware UTC."""
    return AuditRecord(
        seq=row["seq"], event_id=row["event_id"], at=to_utc(row["at"]).replace(tzinfo=UTC),
        actor_user_id=row["actor_user_id"], actor_role=row["actor_role"], on_behalf_of=row["on_behalf_of"],
        action=row["action"], entity_type=row["entity_type"], entity_id=row["entity_id"],
        before=row["before_json"], after=row["after_json"], comment=row["comment"],
        request_id=row["request_id"], prev_hash=row["prev_hash"], hash=row["hash"],
    )


def log_event(
    session: Session,
    *,
    actor_user_id: str,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
    on_behalf_of: str | None = None,
    comment: str | None = None,
    request_id: str | None = None,
    at: datetime | None = None,
) -> AuditRecord:
    """Append one event to the audit chain inside the caller's transaction, and return it.

    Never commits, never closes the session: the event commits or rolls back with the caller's own changes. Only
    structurally invalid input is refused (an empty actor, role, action, entity type or entity id -> ValueError);
    any action string is accepted. before / after are converted with to_audit_json and redacted; digit runs of 7+
    in `comment` are masked. On SQLite the session must be a write session (RuntimeError otherwise). A payload with
    an account number needs AUDIT_HMAC_KEY (AuditKeyError otherwise).

    The insert runs in a SAVEPOINT. If the prev_hash unique index rejects it (another writer extended the same
    event first), the savepoint is rolled back, the latest hash re-read, and the insert retried, up to MAX_ATTEMPTS
    times; then AuditChainConflict is raised. Any other IntegrityError propagates unchanged.
    """
    required = {"actor_user_id": actor_user_id, "actor_role": actor_role, "action": action,
                "entity_type": entity_type, "entity_id": entity_id}
    for name, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"log_event: {name} must be a non-empty string")
    _require_write_session(session)

    values: dict[str, Any] = {
        "event_id": f"EV-{uuid.uuid4().hex}",
        "at": to_utc(at) if at is not None else utcnow(),
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "on_behalf_of": on_behalf_of,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before_json": redact(to_audit_json(before)) if before is not None else None,
        "after_json": redact(to_audit_json(after)) if after is not None else None,
        "comment": mask_digit_runs(comment) if comment is not None else None,
        "request_id": request_id,
    }

    for _attempt in range(MAX_ATTEMPTS):
        values["prev_hash"] = _latest_hash(session)
        values["hash"] = compute_hash(values["prev_hash"], _hash_fields(values))
        try:
            # begin_nested() flushes the caller's pending changes, then opens a SAVEPOINT for just this insert.
            with session.begin_nested():
                seq = session.execute(_table.insert().values(**values).returning(_table.c.seq)).scalar_one()
        except IntegrityError as exc:
            if not _is_prev_hash_conflict(exc):
                raise
            continue  # the savepoint was rolled back; re-read the latest hash and try again
        return _record({**values, "seq": seq})
    raise AuditChainConflict(f"could not append to the audit chain after {MAX_ATTEMPTS} attempts")


# ---------------------------------------------------------------- verifying


def chain_head(session: Session) -> tuple[int, str] | None:
    """(seq, hash) of the newest event, or None when the log is empty.

    verify_chain can't tell if the newest events were deleted. Record the head when exporting (or periodically,
    somewhere the database can't change), and compare it later: the recorded seq must still exist with that hash.
    """
    row = session.execute(select(_table.c.seq, _table.c.hash).order_by(_table.c.seq.desc()).limit(1)).first()
    return (row.seq, row.hash) if row is not None else None


def verify_chain(session: Session) -> ChainReport:
    """Walk every event in seq order, recompute each hash, and check each prev_hash links to the previous event.

    Reports the first bad row: a prev_hash that doesn't match the previous event's hash (a row was deleted,
    inserted or reordered), or a stored hash that doesn't match the row's contents (a row was edited). Rows are
    streamed, not loaded all at once. Limitation: deleting the newest events can't be detected from the chain alone;
    compare against a head recorded earlier with chain_head().
    """
    expected_prev = GENESIS
    count = 0
    first_bad: tuple[int, str] | None = None
    rows = session.execute(select(_table).order_by(_table.c.seq).execution_options(yield_per=CSV_BATCH)).mappings()
    for row in rows:
        count += 1
        if first_bad is None:
            if row["prev_hash"] != expected_prev:
                first_bad = (row["seq"], f"prev_hash {row['prev_hash']!r} does not match the previous event's hash "
                                         f"{expected_prev!r} (an event was deleted, inserted or reordered)")
            elif compute_hash(row["prev_hash"], _hash_fields(row)) != row["hash"]:
                first_bad = (row["seq"], "stored hash does not match the event's contents (the event was changed)")
        expected_prev = row["hash"]
    if first_bad is None:
        return ChainReport(ok=True, count=count)
    return ChainReport(ok=False, count=count, first_bad_seq=first_bad[0], reason=first_bad[1])


# ---------------------------------------------------------------- reading (for the audit API)


def _filtered(*, entity_type: str | None = None, entity_id: str | None = None, actor_user_id: str | None = None,
              action: str | None = None, since: datetime | None = None, until: datetime | None = None,
              after_seq: int | None = None) -> Select:
    """SELECT over audit_events with the given filters, in seq order. since is inclusive, until exclusive (UTC)."""
    query = select(_table).order_by(_table.c.seq)
    for column, value in (("entity_type", entity_type), ("entity_id", entity_id),
                          ("actor_user_id", actor_user_id), ("action", action)):
        if value is not None:
            query = query.where(_table.c[column] == value)
    if since is not None:
        query = query.where(_table.c.at >= to_utc(since))
    if until is not None:
        query = query.where(_table.c.at < to_utc(until))
    if after_seq is not None:
        query = query.where(_table.c.seq > after_seq)
    return query


def _fetch(session: Session, query: Select, limit: int) -> list[RowMapping]:
    """Run a filtered query for at most `limit` rows, as plain row mappings (Core rows, no ORM identity map)."""
    return list(session.execute(query.limit(limit)).mappings())


def list_events(session: Session, *, entity_type: str | None = None, entity_id: str | None = None,
                actor_user_id: str | None = None, action: str | None = None, since: datetime | None = None,
                until: datetime | None = None, after_seq: int | None = None, limit: int = 100) -> list[AuditRecord]:
    """One page of events matching the filters, oldest first.

    Keyset pagination: pass the last returned seq as after_seq to get the next page (no gaps or repeats, even while
    new events are being written). limit is capped at MAX_PAGE; a limit below 1 is a ValueError.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    query = _filtered(entity_type=entity_type, entity_id=entity_id, actor_user_id=actor_user_id, action=action,
                      since=since, until=until, after_seq=after_seq)
    return [_record(row) for row in _fetch(session, query, min(limit, MAX_PAGE))]


CSV_COLUMNS = ("seq", "event_id", "at", "actor_user_id", "actor_role", "on_behalf_of", "action", "entity_type",
               "entity_id", "comment", "before_json", "after_json", "prev_hash", "hash")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: Any) -> str:
    """One CSV cell as text. JSON payloads are compact JSON; text that a spreadsheet would run as a formula (it
    starts with = + - @ tab or CR) is prefixed with a single quote."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        text = _iso_utc(value)
    elif isinstance(value, dict | list):
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    else:
        text = str(value)
    return f"'{text}" if text.startswith(_FORMULA_START) else text


def _csv_line(cells: list[str]) -> str:
    """Format one CSV record (with the csv module, so commas, quotes and newlines are quoted correctly)."""
    buffer = io.StringIO()
    csv.writer(buffer).writerow(cells)
    return buffer.getvalue()


def iter_events_csv(session: Session, *, entity_type: str | None = None, entity_id: str | None = None,
                    actor_user_id: str | None = None, action: str | None = None, since: datetime | None = None,
                    until: datetime | None = None, after_seq: int | None = None) -> Iterator[str]:
    """Stream matching events as CSV: a header record, then one record per event, oldest first.

    Fetches CSV_BATCH rows per query (keyset by seq), so memory stays flat however large the log is. Each yielded
    string is one CSV record ending in CRLF; a record can contain newlines inside a quoted field. The session must
    stay open while the iterator is consumed (e.g. for the whole of a streaming HTTP response).
    """
    yield _csv_line(list(CSV_COLUMNS))
    cursor = after_seq
    while True:
        query = _filtered(entity_type=entity_type, entity_id=entity_id, actor_user_id=actor_user_id, action=action,
                          since=since, until=until, after_seq=cursor)
        batch = _fetch(session, query, CSV_BATCH)
        for row in batch:
            yield _csv_line([_csv_cell(row[column]) for column in CSV_COLUMNS])
        if len(batch) < CSV_BATCH:
            return
        cursor = batch[-1]["seq"]
