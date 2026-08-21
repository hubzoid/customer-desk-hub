"""The desk's own records, in one SQLite file in the hub's private data folder
(`.hubzoid/data/customer-desk.sqlite`, included in Hubzoid backups).

Each case is worked as Hubzoid work items. This store keeps what work items do
not: the bound customer, the facts read from ERPNext with their sources, every
reply revision with its checks, tickets, delivery proposals, exception
decisions, sender bindings, the helpdesk write ledger and the sample outbox.
Resolutions, facts and reply revisions are immutable once written.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, number TEXT UNIQUE NOT NULL, namespace TEXT NOT NULL,
  origin_kind TEXT NOT NULL, surface TEXT NOT NULL, channel_id TEXT, provider TEXT, thread_key TEXT,
  helpdesk_ticket_id TEXT, intake_id TEXT, sender_kind TEXT, sender_key TEXT, sender_display TEXT,
  binding_id TEXT, customer_id TEXT, candidates TEXT, state TEXT NOT NULL, queue TEXT, assignee TEXT,
  claimed_by TEXT, claimed_at REAL, work_item_id TEXT, current_resolution INTEGER, current_reply INTEGER,
  policy_digest TEXT, first_received_at TEXT, first_reply_accepted_at TEXT, resolved_at TEXT,
  reopen_count INTEGER NOT NULL DEFAULT 0, related TEXT NOT NULL DEFAULT '[]', opened_by TEXT,
  synthetic INTEGER NOT NULL DEFAULT 1, note TEXT, revision INTEGER NOT NULL DEFAULT 1,
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE INDEX IF NOT EXISTS cases_state ON cases(namespace, state);
CREATE INDEX IF NOT EXISTS cases_thread ON cases(namespace, channel_id, thread_key);
CREATE TABLE IF NOT EXISTS case_events (
  case_id TEXT NOT NULL, seq INTEGER NOT NULL, source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
  received_at TEXT NOT NULL, sender_key TEXT, sender_display TEXT, subject TEXT, text TEXT NOT NULL,
  attachments TEXT NOT NULL DEFAULT '[]', author_kind TEXT NOT NULL DEFAULT 'customer',
  PRIMARY KEY (case_id, seq), UNIQUE (source_kind, source_ref));
CREATE TABLE IF NOT EXISTS resolutions (
  case_id TEXT NOT NULL, revision INTEGER NOT NULL, trigger TEXT NOT NULL, work_item_id TEXT,
  classifier TEXT, second_opinion TEXT, requests TEXT NOT NULL, actions TEXT NOT NULL,
  resolver TEXT, reviewer TEXT, review_rounds INTEGER NOT NULL DEFAULT 0, policy_digest TEXT, style_digest TEXT,
  kinds_digest TEXT, fact_sheet_digest TEXT, instruction TEXT, today TEXT, created REAL NOT NULL,
  PRIMARY KEY (case_id, revision));
CREATE TABLE IF NOT EXISTS facts (
  case_id TEXT NOT NULL, resolution INTEGER NOT NULL, fact_id TEXT NOT NULL, kind TEXT NOT NULL,
  value TEXT NOT NULL, display TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL,
  PRIMARY KEY (case_id, resolution, fact_id));
CREATE TABLE IF NOT EXISTS replies (
  case_id TEXT NOT NULL, revision INTEGER NOT NULL, resolution INTEGER NOT NULL, author_kind TEXT NOT NULL,
  author TEXT, source_md TEXT NOT NULL, rendered TEXT NOT NULL, language TEXT NOT NULL,
  recipients TEXT NOT NULL DEFAULT '[]', subject TEXT, attachments TEXT NOT NULL DEFAULT '[]',
  digest TEXT NOT NULL, checks TEXT NOT NULL, typed_values TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY (case_id, revision));
CREATE TABLE IF NOT EXISTS sends (
  case_id TEXT NOT NULL, reply_revision INTEGER NOT NULL, mode TEXT NOT NULL, synthetic INTEGER NOT NULL,
  provider_draft_id TEXT, work_item_id TEXT, operation_id TEXT, outbox_id TEXT, status TEXT NOT NULL,
  receipt TEXT, requested_by TEXT, created REAL NOT NULL, updated REAL NOT NULL,
  PRIMARY KEY (case_id, reply_revision, mode));
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY, number TEXT UNIQUE NOT NULL, case_id TEXT NOT NULL, severity TEXT NOT NULL,
  owner_role TEXT NOT NULL, assignee TEXT, state TEXT NOT NULL, summary TEXT NOT NULL, reason TEXT,
  revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ticket_notes (
  ticket_id TEXT NOT NULL, seq INTEGER NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL, at REAL NOT NULL,
  PRIMARY KEY (ticket_id, seq));
CREATE TABLE IF NOT EXISTS delivery_proposals (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, sales_order TEXT NOT NULL, scope TEXT NOT NULL,
  observed_date TEXT, requested_date TEXT NOT NULL, state TEXT NOT NULL, decided_by TEXT, note TEXT,
  verified TEXT, revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, kind TEXT NOT NULL, inputs TEXT NOT NULL, state TEXT NOT NULL,
  note TEXT, decided_by TEXT, decided_at REAL, revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bindings (
  id TEXT PRIMARY KEY, company TEXT NOT NULL, channel_kind TEXT NOT NULL, sender_key TEXT NOT NULL,
  customer_id TEXT NOT NULL, state TEXT NOT NULL, source_ref TEXT, synthetic INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created REAL NOT NULL, revoked_by TEXT, revoked REAL, revision INTEGER NOT NULL DEFAULT 1);
CREATE UNIQUE INDEX IF NOT EXISTS bindings_active ON bindings(company, channel_kind, sender_key, customer_id)
  WHERE state = 'active';
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS owner_keys (
  case_id TEXT NOT NULL, key TEXT NOT NULL, kind TEXT NOT NULL, ref_id TEXT NOT NULL, PRIMARY KEY (case_id, key));
CREATE TABLE IF NOT EXISTS attachments (
  sha256 TEXT PRIMARY KEY, name TEXT NOT NULL, media_type TEXT NOT NULL, bytes INTEGER NOT NULL, path TEXT NOT NULL,
  created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS helpdesk_tickets (
  ticket_id TEXT PRIMARY KEY, number TEXT, case_id TEXT, observed_modified TEXT, latest_inbound_id TEXT,
  handled_message_id TEXT, status TEXT NOT NULL DEFAULT 'pending', owner TEXT, claimed_at REAL, updated REAL);
CREATE TABLE IF NOT EXISTS helpdesk_writes (
  idem_key TEXT PRIMARY KEY, kind TEXT NOT NULL, mode TEXT NOT NULL, ticket_id TEXT NOT NULL, case_id TEXT,
  request TEXT NOT NULL, response TEXT, status TEXT NOT NULL, error TEXT, owner TEXT, claimed_at REAL,
  attempts INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS cursor (name TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, reply_revision INTEGER NOT NULL, channel_id TEXT NOT NULL,
  channel_kind TEXT NOT NULL, recipients TEXT NOT NULL, subject TEXT, body TEXT NOT NULL,
  attachments TEXT NOT NULL, digest TEXT NOT NULL, idem_key TEXT UNIQUE NOT NULL, accepted_at TEXT NOT NULL,
  approved_by TEXT);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  subject TEXT, detail TEXT);
"""

JSON_COLUMNS = {"candidates", "related", "attachments", "classifier", "second_opinion", "requests", "actions",
                "resolver", "reviewer", "value", "source", "recipients", "checks", "typed_values", "receipt",
                "scope", "observed_date", "verified", "inputs", "request", "response", "detail"}

_LOCAL = threading.local()


def db_path(hub_dir: Path) -> Path:
    override = os.environ.get("DESK_DB")
    if override:
        return Path(override)
    try:
        from hubzoid.datadir import state

        base = state(Path(hub_dir)) / "data"
    except ImportError:  # pragma: no cover - the SDK is always installed with the hub
        base = Path(hub_dir) / ".hubzoid" / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / "customer-desk.sqlite"


def connect(hub_dir: Path) -> sqlite3.Connection:
    path = db_path(hub_dir)
    key = str(path)
    cache = getattr(_LOCAL, "conns", None)
    if cache is None:
        cache = _LOCAL.conns = {}
    conn = cache.get(key)
    if conn is None:
        conn = sqlite3.connect(key, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        cache[key] = conn
    return conn


def reset_connections() -> None:
    for conn in (getattr(_LOCAL, "conns", None) or {}).values():
        with contextlib.suppress(Exception):
            conn.close()
    _LOCAL.conns = {}


@contextlib.contextmanager
def tx(hub_dir: Path):
    """One write transaction, taken immediately so counters never race."""
    conn = connect(hub_dir)
    for attempt in range(20):
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def dumps(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    out = dict(r)
    for k, v in out.items():
        if k in JSON_COLUMNS and isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except ValueError:
                pass
    return out


def rows(cursor) -> list[dict]:
    return [row(r) for r in cursor.fetchall()]


def new_id() -> str:
    return str(uuid.uuid4())


def next_number(conn: sqlite3.Connection, name: str, prefix: str) -> str:
    """The next display number, inside the caller's transaction."""
    cur = conn.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
    value = (cur["value"] if cur else 0) + 1
    conn.execute("INSERT INTO counters(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                 (name, value))
    return f"{prefix}-{value:06d}"


def audit(conn: sqlite3.Connection, actor: str, action: str, subject: str | None = None, detail=None) -> None:
    conn.execute("INSERT INTO audit(at, actor, action, subject, detail) VALUES (?,?,?,?,?)",
                 (time.time(), actor or "system", action, subject, dumps(detail or {})))


class Conflict(Exception):
    """A stale revision or a state that no longer allows the change."""

    def __init__(self, code: str, message: str, **fields):
        super().__init__(message)
        self.code, self.message, self.fields = code, message, fields


# -- cases ---------------------------------------------------------------------------

CASE_FIELDS = {"namespace", "origin_kind", "surface", "channel_id", "provider", "thread_key", "helpdesk_ticket_id",
               "intake_id", "sender_kind", "sender_key", "sender_display", "binding_id", "customer_id",
               "candidates", "state", "queue", "assignee", "claimed_by", "claimed_at", "work_item_id",
               "current_resolution", "current_reply", "policy_digest", "first_received_at",
               "first_reply_accepted_at", "resolved_at", "reopen_count", "related", "opened_by", "synthetic", "note"}


def create_case(conn, *, prefix: str, **fields) -> dict:
    unknown = set(fields) - CASE_FIELDS
    if unknown:
        raise ValueError(f"unknown case fields {sorted(unknown)}")
    cid = new_id()
    number = next_number(conn, f"case:{fields.get('namespace', 'sample')}", prefix)
    now = time.time()
    data = {k: (dumps(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
    cols = ["id", "number", "created", "updated", *data]
    conn.execute(f"INSERT INTO cases({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 (cid, number, now, now, *data.values()))
    return get_case(conn, cid)


def get_case(conn, case_id_or_number: str) -> dict | None:
    return row(conn.execute("SELECT * FROM cases WHERE id=? OR number=?",
                            (case_id_or_number, case_id_or_number)).fetchone())


def update_case(conn, case_id: str, *, expected_revision: int | None = None, expect_states=None, **fields) -> dict:
    unknown = set(fields) - CASE_FIELDS
    if unknown:
        raise ValueError(f"unknown case fields {sorted(unknown)}")
    current = get_case(conn, case_id)
    if current is None:
        raise Conflict("not_found", "No such case.")
    if expected_revision is not None and current["revision"] != expected_revision:
        raise Conflict("revision_conflict", "Someone changed this case since you loaded it. Reload and try again.",
                       current_revision=current["revision"])
    if expect_states is not None and current["state"] not in expect_states:
        raise Conflict("state_conflict", f"The case is {current['state']}, so this change no longer applies.",
                       state=current["state"])
    data = {k: (dumps(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE cases SET {sets}{', ' if sets else ''}revision=revision+1, updated=? WHERE id=?",
                 (*data.values(), time.time(), current["id"]))
    return get_case(conn, current["id"])


def list_cases(conn, *, namespace: str, state: str | None = None, queue: str | None = None,
               customer: str | None = None, limit: int = 25, offset: int = 0) -> list[dict]:
    where, args = ["namespace=?"], [namespace]
    if state:
        where.append("state=?")
        args.append(state)
    if queue:
        where.append("queue=?")
        args.append(queue)
    if customer:
        where.append("customer_id=?")
        args.append(customer)
    sql = f"SELECT * FROM cases WHERE {' AND '.join(where)} ORDER BY number LIMIT ? OFFSET ?"
    return rows(conn.execute(sql, (*args, max(1, min(limit, 100)), max(0, offset))))


def add_event(conn, case_id: str, *, source_kind: str, source_ref: str, received_at: str, text: str,
              sender_key: str | None = None, sender_display: str | None = None, subject: str | None = None,
              attachments=None, author_kind: str = "customer") -> tuple[dict, bool]:
    """Attach one message to a case. The same source reference twice is a no-op."""
    existing = conn.execute("SELECT * FROM case_events WHERE source_kind=? AND source_ref=?",
                            (source_kind, source_ref)).fetchone()
    if existing is not None:
        return row(existing), False
    seq = (conn.execute("SELECT COALESCE(MAX(seq), 0) AS n FROM case_events WHERE case_id=?", (case_id,))
           .fetchone()["n"]) + 1
    conn.execute("INSERT INTO case_events(case_id, seq, source_kind, source_ref, received_at, sender_key, "
                 "sender_display, subject, text, attachments, author_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (case_id, seq, source_kind, source_ref, received_at, sender_key, sender_display, subject, text,
                  dumps(attachments or []), author_kind))
    return row(conn.execute("SELECT * FROM case_events WHERE case_id=? AND seq=?", (case_id, seq)).fetchone()), True


def events(conn, case_id: str) -> list[dict]:
    return rows(conn.execute("SELECT * FROM case_events WHERE case_id=? ORDER BY seq", (case_id,)))


# -- resolutions, facts, replies -------------------------------------------------------

def next_resolution(conn, case_id: str) -> int:
    return (conn.execute("SELECT COALESCE(MAX(revision), 0) AS n FROM resolutions WHERE case_id=?", (case_id,))
            .fetchone()["n"]) + 1


def save_resolution(conn, case_id: str, revision: int, **fields) -> dict:
    data = {k: (dumps(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
    cols = ["case_id", "revision", "created", *data]
    conn.execute(f"INSERT OR IGNORE INTO resolutions({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 (case_id, revision, time.time(), *data.values()))
    return get_resolution(conn, case_id, revision)


def get_resolution(conn, case_id: str, revision: int) -> dict | None:
    return row(conn.execute("SELECT * FROM resolutions WHERE case_id=? AND revision=?", (case_id, revision)).fetchone())


def save_facts(conn, case_id: str, resolution: int, facts: list[dict]) -> None:
    for f in facts:
        conn.execute("INSERT OR IGNORE INTO facts(case_id, resolution, fact_id, kind, value, display, source, "
                     "observed_at) VALUES (?,?,?,?,?,?,?,?)",
                     (case_id, resolution, f["fact_id"], f["kind"], dumps(f["value"]), f["display"],
                      dumps(f["source"]), f["observed_at"]))


def get_facts(conn, case_id: str, resolution: int) -> list[dict]:
    return rows(conn.execute("SELECT * FROM facts WHERE case_id=? AND resolution=? ORDER BY CAST(SUBSTR(fact_id, 2) "
                             "AS INTEGER)", (case_id, resolution)))


def next_reply(conn, case_id: str) -> int:
    return (conn.execute("SELECT COALESCE(MAX(revision), 0) AS n FROM replies WHERE case_id=?", (case_id,))
            .fetchone()["n"]) + 1


def save_reply(conn, case_id: str, revision: int, **fields) -> dict:
    data = {k: (dumps(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
    cols = ["case_id", "revision", "created", *data]
    conn.execute(f"INSERT INTO replies({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 (case_id, revision, time.time(), *data.values()))
    return get_reply(conn, case_id, revision)


def get_reply(conn, case_id: str, revision: int) -> dict | None:
    return row(conn.execute("SELECT * FROM replies WHERE case_id=? AND revision=?", (case_id, revision)).fetchone())


def replies(conn, case_id: str) -> list[dict]:
    return rows(conn.execute("SELECT * FROM replies WHERE case_id=? ORDER BY revision", (case_id,)))


def set_reply_state(conn, case_id: str, revision: int, state: str, *, expect=None) -> None:
    cur = get_reply(conn, case_id, revision)
    if cur is None:
        raise Conflict("not_found", "No such reply revision.")
    if expect is not None and cur["state"] not in expect:
        raise Conflict("reply_stale", f"Reply {revision} is {cur['state']}.", state=cur["state"])
    conn.execute("UPDATE replies SET state=? WHERE case_id=? AND revision=?", (state, case_id, revision))


# -- owner items -------------------------------------------------------------------

def create_ticket(conn, *, prefix: str, case_id: str, severity: str, owner_role: str, summary: str,
                  reason: str | None = None) -> dict:
    tid = new_id()
    number = next_number(conn, "ticket", prefix)
    now = time.time()
    conn.execute("INSERT INTO tickets(id, number, case_id, severity, owner_role, state, summary, reason, created, "
                 "updated) VALUES (?,?,?,?,?,'open',?,?,?,?)",
                 (tid, number, case_id, severity, owner_role, summary, reason, now, now))
    return get_ticket(conn, tid)


def get_ticket(conn, ticket_id_or_number: str) -> dict | None:
    return row(conn.execute("SELECT * FROM tickets WHERE id=? OR number=?",
                            (ticket_id_or_number, ticket_id_or_number)).fetchone())


def case_tickets(conn, case_id: str) -> list[dict]:
    return rows(conn.execute("SELECT * FROM tickets WHERE case_id=? ORDER BY number", (case_id,)))


def add_ticket_note(conn, ticket_id: str, author: str, body: str) -> None:
    seq = (conn.execute("SELECT COALESCE(MAX(seq), 0) AS n FROM ticket_notes WHERE ticket_id=?", (ticket_id,))
           .fetchone()["n"]) + 1
    conn.execute("INSERT INTO ticket_notes(ticket_id, seq, author, body, at) VALUES (?,?,?,?,?)",
                 (ticket_id, seq, author, body, time.time()))


def ticket_notes(conn, ticket_id: str) -> list[dict]:
    return rows(conn.execute("SELECT * FROM ticket_notes WHERE ticket_id=? ORDER BY seq", (ticket_id,)))


def update_ticket(conn, ticket_id: str, *, expected_revision: int | None = None, **fields) -> dict:
    cur = get_ticket(conn, ticket_id)
    if cur is None:
        raise Conflict("not_found", "No such ticket.")
    if expected_revision is not None and cur["revision"] != expected_revision:
        raise Conflict("revision_conflict", "The ticket changed since you loaded it.", current_revision=cur["revision"])
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE tickets SET {sets}, revision=revision+1, updated=? WHERE id=?",
                 (*fields.values(), time.time(), cur["id"]))
    return get_ticket(conn, cur["id"])


def create_proposal(conn, *, case_id: str, sales_order: str, scope, observed_date, requested_date: str) -> dict:
    pid = new_id()
    now = time.time()
    conn.execute("INSERT INTO delivery_proposals(id, case_id, sales_order, scope, observed_date, requested_date, "
                 "state, created, updated) VALUES (?,?,?,?,?,?,'proposed',?,?)",
                 (pid, case_id, sales_order, dumps(scope), dumps(observed_date), requested_date, now, now))
    return get_proposal(conn, pid)


def get_proposal(conn, pid: str) -> dict | None:
    return row(conn.execute("SELECT * FROM delivery_proposals WHERE id=? OR id LIKE ?", (pid, f"{pid}%")).fetchone())


def case_proposals(conn, case_id: str) -> list[dict]:
    return rows(conn.execute("SELECT * FROM delivery_proposals WHERE case_id=? ORDER BY created", (case_id,)))


def update_proposal(conn, pid: str, *, expect_states=None, **fields) -> dict:
    cur = get_proposal(conn, pid)
    if cur is None:
        raise Conflict("not_found", "No such delivery proposal.")
    if expect_states and cur["state"] not in expect_states:
        raise Conflict("state_conflict", f"The proposal is already {cur['state']}.", state=cur["state"])
    data = {k: (dumps(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE delivery_proposals SET {sets}, revision=revision+1, updated=? WHERE id=?",
                 (*data.values(), time.time(), cur["id"]))
    return get_proposal(conn, cur["id"])


def create_decision(conn, *, case_id: str, kind: str, inputs: dict) -> dict:
    did = new_id()
    conn.execute("INSERT INTO decisions(id, case_id, kind, inputs, state, created) VALUES (?,?,?,?,'pending',?)",
                 (did, case_id, kind, dumps(inputs), time.time()))
    return get_decision(conn, did)


def get_decision(conn, did: str) -> dict | None:
    return row(conn.execute("SELECT * FROM decisions WHERE id=? OR id LIKE ?", (did, f"{did}%")).fetchone())


def case_decisions(conn, case_id: str) -> list[dict]:
    return rows(conn.execute("SELECT * FROM decisions WHERE case_id=? ORDER BY created", (case_id,)))


def decide(conn, did: str, *, state: str, note: str, by: str) -> dict:
    cur = get_decision(conn, did)
    if cur is None:
        raise Conflict("not_found", "No such decision.")
    if cur["state"] != "pending":
        raise Conflict("state_conflict", f"This decision was already {cur['state']} by {cur['decided_by']}.")
    conn.execute("UPDATE decisions SET state=?, note=?, decided_by=?, decided_at=?, revision=revision+1 WHERE id=?",
                 (state, note, by, time.time(), cur["id"]))
    return get_decision(conn, cur["id"])


# -- sends and the sample outbox ---------------------------------------------------------

def upsert_send(conn, case_id: str, reply_revision: int, mode: str, **fields) -> dict:
    now = time.time()
    existing = conn.execute("SELECT * FROM sends WHERE case_id=? AND reply_revision=? AND mode=?",
                            (case_id, reply_revision, mode)).fetchone()
    data = {k: (dumps(v) if k in JSON_COLUMNS else v) for k, v in fields.items()}
    if existing is None:
        cols = ["case_id", "reply_revision", "mode", "created", "updated", *data]
        conn.execute(f"INSERT INTO sends({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                     (case_id, reply_revision, mode, now, now, *data.values()))
    elif data:
        sets = ", ".join(f"{k}=?" for k in data)
        conn.execute(f"UPDATE sends SET {sets}, updated=? WHERE case_id=? AND reply_revision=? AND mode=?",
                     (*data.values(), now, case_id, reply_revision, mode))
    return row(conn.execute("SELECT * FROM sends WHERE case_id=? AND reply_revision=? AND mode=?",
                            (case_id, reply_revision, mode)).fetchone())


def case_sends(conn, case_id: str) -> list[dict]:
    return rows(conn.execute("SELECT * FROM sends WHERE case_id=? ORDER BY reply_revision", (case_id,)))
