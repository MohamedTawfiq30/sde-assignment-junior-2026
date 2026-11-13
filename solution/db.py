"""SQLite storage for Assignment A. Stdlib ``sqlite3`` only.

Schema
------
- ``dispositions`` — the catalogue from ``dispositions.csv``.
- ``leads`` — one row per lead, keyed by (workflow_id, phone_hash).
  No PII in plaintext: phone is a salted hash + masked form, the customer
  name is a salted hash, and ``fields_json`` holds only non-PII fields
  (reference, dates, amounts, language, product).
- ``events`` — the append-only interaction ledger. One row per event,
  keyed by ``event_id`` (``INSERT OR IGNORE`` gives dedupe for free).
  ``linked`` = 1 once the event is attached to a lead; 0 while it is an
  orphan (e.g. its lead has not arrived yet). Rows are never updated
  except for the ``linked``/``phone_hash`` columns on re-link, and never
  deleted — overrides are new rows, never edits.
- ``rejections`` — rejected lead rows (no PII: workflow, batch, row, reason).
- ``ingest_state`` — every file already ingested. Re-running ``ingest``
  on a drop skips these files, which is what makes re-ingest a no-op.
- ``counters`` — running totals for ``data_quality.json``. Only ever
  incremented while ingesting a file for the first time.
"""
from __future__ import annotations

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS dispositions (
    workflow_id TEXT NOT NULL,
    code TEXT NOT NULL,
    is_terminal INTEGER NOT NULL,
    is_success INTEGER NOT NULL,
    PRIMARY KEY (workflow_id, code)
);
CREATE TABLE IF NOT EXISTS leads (
    workflow_id TEXT NOT NULL,
    phone_hash TEXT NOT NULL,
    phone_masked TEXT NOT NULL,
    name_hash TEXT,
    external_ref TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    fields_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (workflow_id, phone_hash)
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    phone_hash TEXT,
    disposition_code TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    linked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_call ON events(call_id);
CREATE INDEX IF NOT EXISTS idx_events_phone ON events(phone_hash);
CREATE TABLE IF NOT EXISTS rejections (
    workflow_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (workflow_id, batch_id, row_number)
);
CREATE TABLE IF NOT EXISTS ingest_state (
    file_path TEXT PRIMARY KEY,
    drop_name TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""

COUNTER_KEYS = (
    "lead_rows_total",
    "lead_rows_rejected",
    "duplicate_lead_rows_merged",
    "field_warnings",
    "events_total",
    "malformed_events",
    "duplicate_events_dropped",
    "unknown_disposition_events",
)


def connect(db_path: str) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite DB and ensure the schema."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for key in COUNTER_KEYS:
        conn.execute(
            "INSERT OR IGNORE INTO counters (key, value) VALUES (?, 0)", (key,))
    conn.commit()
    return conn


def bump(conn: sqlite3.Connection, key: str, amount: int = 1) -> None:
    conn.execute(
        "UPDATE counters SET value = value + ? WHERE key = ?", (amount, key))


def get_counters(conn: sqlite3.Connection) -> dict:
    return {row["key"]: row["value"]
            for row in conn.execute("SELECT key, value FROM counters")}


def already_ingested(conn: sqlite3.Connection, file_path: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ingest_state WHERE file_path = ?",
        (os.path.abspath(file_path),)).fetchone()
    return row is not None


def mark_ingested(conn: sqlite3.Connection, file_path: str,
                  drop_name: str, now_iso: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO ingest_state (file_path, drop_name, "
        "ingested_at_utc) VALUES (?, ?, ?)",
        (os.path.abspath(file_path), drop_name, now_iso))
