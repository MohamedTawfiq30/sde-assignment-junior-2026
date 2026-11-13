"""Ingestion for Assignment A: lead CSVs + event JSONL into SQLite.

Order of operations per drop (spec): lead files first (drops in ingest
order, files in filename order, rows in file order), then event files in
filename order. After a drop, previously orphaned events are retried —
a lead arriving in ``drop_2`` can rescue an event that was an orphan
after ``drop_1``.

Idempotency: every file is recorded in ``ingest_state`` once fully
processed (same transaction as its rows). Re-running ``ingest`` on a
drop skips those files entirely, so counters and tables do not change.

Core rules are implemented in ``rules.py`` and called directly.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

from . import db, rules
from .normalize import map_headers, normalize_phone, parse_event_ts, parse_field
from .pii import mask_phone, name_hash, phone_hash

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(REPO_ROOT, "assignment-a-data", "schemas")


def load_schemas() -> dict:
    """{workflow_id: schema dict} from assignment-a-data/schemas/*.json."""
    schemas = {}
    for filename in sorted(os.listdir(SCHEMAS_DIR)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(SCHEMAS_DIR, filename), encoding="utf-8") as f:
            schema = json.load(f)
        schemas[schema["workflow_id"]] = schema
    return schemas


def load_dispositions(conn) -> set:
    """Load dispositions.csv into the DB; return {(workflow_id, code)}."""
    path = os.path.join(SCHEMAS_DIR, "dispositions.csv")
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute(
                "INSERT OR IGNORE INTO dispositions "
                "(workflow_id, code, is_terminal, is_success) "
                "VALUES (?, ?, ?, ?)",
                (row["workflow_id"], row["code"],
                 row["is_terminal"].strip().lower() == "true",
                 row["is_success"].strip().lower() == "true"))
    conn.commit()
    return {(r["workflow_id"], r["code"]) for r in
            conn.execute("SELECT workflow_id, code FROM dispositions")}


def reference_field(schema: dict) -> str:
    for field in schema["fields"]:
        if field.get("reference"):
            return field["name"]
    raise ValueError(f"schema {schema['workflow_id']} has no reference field")


def _non_pii_fields(schema: dict, parsed: dict) -> dict:
    """Field values safe to store: everything except PII (name, phone)."""
    pii_names = {f["name"] for f in schema["fields"] if f.get("pii")}
    return {k: v for k, v in parsed.items() if k not in pii_names}


def apply_defaults(schema: dict, fields: dict) -> dict:
    """Spec: defaults apply after merging, to fields that are still null."""
    out = dict(fields)
    for field in schema["fields"]:
        if "default" in field and out.get(field["name"]) is None:
            out[field["name"]] = field["default"]
    return out


def _validate_row(schema: dict, values: dict):
    """Validate one lead row. Spec: walk the fields in schema order; the
    first failure becomes the row's single reason:
    - required field missing -> ``missing_required:<field_name>``
    - phone present but invalid -> ``invalid_phone``
    An optional field present but invalid -> null + one field warning
    (only counted for rows that are not rejected).

    Returns ``(parsed_dict, rejection_reason_or_None, warnings)``.
    """
    parsed = {}
    warnings = 0
    for field in schema["fields"]:
        name = field["name"]
        raw = values.get(name)
        missing = raw is None or str(raw).strip() == ""
        if missing:
            if field.get("required"):
                return None, f"missing_required:{name}", 0
            parsed[name] = None
            continue
        value = parse_field(field["type"], raw, field)
        if value is None:
            if field["type"] == "phone":
                return None, "invalid_phone", 0
            parsed[name] = None
            warnings += 1
        else:
            parsed[name] = value
    return parsed, None, warnings


def ingest_lead_file(conn, schema: dict, path: str, batch_id: str) -> None:
    workflow_id = schema["workflow_id"]
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        colmap = map_headers(reader.fieldnames, schema["fields"])
        row_number = 0
        for raw_row in reader:
            cells = [v for v in raw_row.values() if v is not None]
            if all(str(c).strip() == "" for c in cells):
                continue  # blank rows are skipped and not counted
            row_number += 1
            db.bump(conn, "lead_rows_total")
            values = {name: raw_row.get(col) for name, col in colmap.items()}
            parsed, rejection, warnings = _validate_row(schema, values)
            if rejection is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO rejections "
                    "(workflow_id, batch_id, row_number, reason) "
                    "VALUES (?, ?, ?, ?)",
                    (workflow_id, batch_id, row_number, rejection))
                db.bump(conn, "lead_rows_rejected")
                continue
            db.bump(conn, "field_warnings", warnings)
            canonical = parsed["phone"]
            hashed = phone_hash(canonical)
            ref = parsed[reference_field(schema)]
            name = parsed.get("customer_name")
            fields = _non_pii_fields(schema, parsed)
            existing = conn.execute(
                "SELECT fields_json FROM leads WHERE workflow_id = ? "
                "AND phone_hash = ?", (workflow_id, hashed)).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO leads (workflow_id, phone_hash, "
                    "phone_masked, name_hash, external_ref, batch_id, "
                    "fields_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (workflow_id, hashed, mask_phone(canonical),
                     name_hash(name) if name else None, ref, batch_id,
                     json.dumps(fields)))
            else:
                db.bump(conn, "duplicate_lead_rows_merged")
                merged = rules.merge_duplicate(
                    json.loads(existing["fields_json"]), fields)
                conn.execute(
                    "UPDATE leads SET fields_json = ?, external_ref = ?, "
                    "name_hash = COALESCE(?, name_hash) "
                    "WHERE workflow_id = ? AND phone_hash = ?",
                    (json.dumps(merged), ref,
                     name_hash(name) if name else None,
                     workflow_id, hashed))
    conn.commit()


def _lead_exists(conn, workflow_id: str, hashed: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM leads WHERE workflow_id = ? AND phone_hash = ?",
        (workflow_id, hashed)).fetchone() is not None


def _lead_hash_by_call(conn, call_id: str):
    row = conn.execute(
        "SELECT phone_hash FROM events WHERE call_id = ? AND linked = 1 "
        "AND phone_hash IS NOT NULL ORDER BY occurred_at_utc LIMIT 1",
        (call_id,)).fetchone()
    return row["phone_hash"] if row else None


def _link(conn, event: dict, workflow_id: str, event_phone_hash=None):
    """Link one event; returns phone_hash or None. ``event_phone_hash``
    is the salted hash of the event's normalised phone (None when the
    event carries no phone)."""
    if event_phone_hash is None and event.get("phone"):
        canonical = normalize_phone(event["phone"])
        if canonical is not None:
            event_phone_hash = phone_hash(canonical)
    return rules.link_event(
        event, event_phone_hash,
        lambda h: _lead_exists(conn, workflow_id, h),
        lambda cid: _lead_hash_by_call(conn, cid))


def ingest_event_file(conn, path: str, dispositions: set) -> None:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip() == "":
                continue
            db.bump(conn, "events_total")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                db.bump(conn, "malformed_events")
                continue
            if (not isinstance(event, dict) or not event.get("event_id")
                    or not event.get("workflow_id")
                    or not event.get("call_id")
                    or not event.get("occurred_at")):
                db.bump(conn, "malformed_events")
                continue
            occurred = parse_event_ts(event["occurred_at"])
            if occurred is None:
                db.bump(conn, "malformed_events")
                continue
            exists = conn.execute(
                "SELECT 1 FROM events WHERE event_id = ?",
                (event["event_id"],)).fetchone()
            if exists is not None:
                db.bump(conn, "duplicate_events_dropped")
                continue
            payload = event.get("payload") or {}
            code = payload.get("disposition_code")
            if event["event_type"] in ("disposition.set",
                                       "disposition.override"):
                if (event["workflow_id"], code) not in dispositions:
                    db.bump(conn, "unknown_disposition_events")
                    continue
            linked_hash = _link(conn, event, event["workflow_id"])
            # Store the phone hash even for orphans (a hash is not PII):
            # it is what lets a later drop re-link the event once its
            # lead arrives. ``linked`` records whether it links *now*.
            stored_hash = linked_hash
            if stored_hash is None and event.get("phone"):
                canonical = normalize_phone(event["phone"])
                if canonical is not None:
                    stored_hash = phone_hash(canonical)
            conn.execute(
                "INSERT INTO events (event_id, workflow_id, call_id, "
                "event_type, occurred_at_utc, phone_hash, disposition_code, "
                "payload_json, linked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event["event_id"], event["workflow_id"], event["call_id"],
                 event["event_type"], occurred.isoformat(),
                 stored_hash, code, json.dumps(payload),
                 1 if linked_hash is not None else 0))
    conn.commit()


def relink_orphans(conn) -> None:
    """Retry previously orphaned events — their lead may have arrived in
    a later drop. Spec: orphan counts in data_quality.json reflect the
    final state.

    Runs to a FIXPOINT: an override links via its call's other events,
    so it can only link once that call's initiated event is linked. A
    single pass can leave overrides stranded behind the events they
    depend on; repeat until a full pass links nothing new.
    """
    for _ in range(10):  # fixpoint; chains here are at most 2 deep
        rows = conn.execute(
            "SELECT * FROM events WHERE linked = 0").fetchall()
        if not rows:
            return
        orphans = [{
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "workflow_id": row["workflow_id"],
            "call_id": row["call_id"],
            "phone_hash": row["phone_hash"],
        } for row in rows]

        def link_fn(orphan):
            return rules.link_event(
                orphan, orphan["phone_hash"],
                lambda h: _lead_exists(conn, orphan["workflow_id"], h),
                lambda cid: _lead_hash_by_call(conn, cid))

        linked = rules.relink_orphans(orphans, link_fn)
        if not linked:
            return
        for event_id, hashed in linked.items():
            conn.execute(
                "UPDATE events SET linked = 1, phone_hash = ? "
                "WHERE event_id = ?", (hashed, event_id))
        conn.commit()


def ingest_drop(db_path: str, drop_dir: str) -> None:
    """Ingest one drop directory (``data/drop_1``). Files already
    recorded in ``ingest_state`` are skipped, so re-ingest is a no-op."""
    conn = db.connect(db_path)
    try:
        schemas = load_schemas()
        dispositions = load_dispositions(conn)
        drop_name = os.path.basename(os.path.normpath(drop_dir))
        now_iso = datetime.now(timezone.utc).isoformat()
        leads_dir = os.path.join(drop_dir, "leads")
        if os.path.isdir(leads_dir):
            for workflow_id in sorted(os.listdir(leads_dir)):
                schema = schemas.get(workflow_id)
                if schema is None:
                    continue
                wf_dir = os.path.join(leads_dir, workflow_id)
                for filename in sorted(os.listdir(wf_dir)):
                    if not filename.endswith(".csv"):
                        continue
                    path = os.path.join(wf_dir, filename)
                    if db.already_ingested(conn, path):
                        continue
                    batch_id = os.path.splitext(filename)[0]
                    ingest_lead_file(conn, schema, path, batch_id)
                    db.mark_ingested(conn, path, drop_name, now_iso)
        events_dir = os.path.join(drop_dir, "events")
        if os.path.isdir(events_dir):
            for filename in sorted(os.listdir(events_dir)):
                if not filename.endswith(".jsonl"):
                    continue
                path = os.path.join(events_dir, filename)
                if db.already_ingested(conn, path):
                    continue
                ingest_event_file(conn, path, dispositions)
                db.mark_ingested(conn, path, drop_name, now_iso)
        conn.commit()
        relink_orphans(conn)
    finally:
        conn.close()
