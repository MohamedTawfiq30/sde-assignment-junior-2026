"""Report writer for Assignment A — the five output files, exactly per spec.

CSVs use a header row, ``,`` delimiter, ``\\n`` line endings, no index
column. Booleans are ``true``/``false``. Sort orders are exactly as
stated in the spec. ``connectivity_rate`` has exactly 4 decimals.
``last_call_at`` is ISO-8601 in IST.

Derived facts (effective disposition, bucket) are called through
``rules.py`` (implemented — see ``rules.py``).
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

from . import db, rules
from .normalize import ist_date, ist_iso


def _dispositions(conn):
    """{(workflow_id, code): (is_terminal, is_success)}"""
    return {(r["workflow_id"], r["code"]):
            (bool(r["is_terminal"]), bool(r["is_success"]))
            for r in conn.execute(
                "SELECT workflow_id, code, is_terminal, is_success "
                "FROM dispositions")}


def _effective_disposition(call_events, occurred_key="occurred_at"):
    """Call rules.effective_disposition (implemented in rules.py)."""
    events = [{
        "event_type": e["event_type"],
        "occurred_at": e[occurred_key],
        "payload": {"disposition_code": e["disposition_code"]},
    } for e in call_events if e["event_type"].startswith("disposition.")]
    return rules.effective_disposition(events)


def _bucket(calls, is_terminal):
    """Call rules.bucket (implemented in rules.py)."""
    return rules.bucket(calls, is_terminal)


def build_reports(db_path: str, out_dir: str) -> None:
    conn = db.connect(db_path)
    try:
        dispositions = _dispositions(conn)
        from .ingest import load_schemas
        schemas = load_schemas()

        # ---- load leads (defaults applied after merging) ----
        leads = []
        for row in conn.execute(
                "SELECT * FROM leads ORDER BY workflow_id, external_ref"):
            fields = json.loads(row["fields_json"])
            schema = schemas[row["workflow_id"]]
            for field in schema["fields"]:
                if "default" in field and fields.get(field["name"]) is None:
                    fields[field["name"]] = field["default"]
            leads.append({
                "workflow_id": row["workflow_id"],
                "phone_hash": row["phone_hash"],
                "phone_masked": row["phone_masked"],
                "external_ref": row["external_ref"],
                "batch_id": row["batch_id"],
                "fields": fields,
            })
        lead_by_hash = {(l["workflow_id"], l["phone_hash"]): l for l in leads}

        # ---- load linked events, group into calls ----
        # A call is counted only if its call.initiated event is present
        # (and linked). The call's date is the IST date of call.initiated.
        calls = {}  # call_id -> dict
        for row in conn.execute(
                "SELECT * FROM events WHERE linked = 1 "
                "ORDER BY occurred_at_utc"):
            occurred = datetime.fromisoformat(
                row["occurred_at_utc"]).replace(tzinfo=timezone.utc)
            call = calls.setdefault(row["call_id"], {
                "workflow_id": row["workflow_id"],
                "phone_hash": row["phone_hash"],
                "initiated_at": None,
                "connected": False,
                "telephony_failed": False,
                "disposition_events": [],
            })
            if row["event_type"] == "call.initiated":
                if (call["initiated_at"] is None
                        or occurred < call["initiated_at"]):
                    call["initiated_at"] = occurred
            elif row["event_type"] == "call.connected":
                call["connected"] = True
            elif row["event_type"] == "call.telephony_failed":
                call["telephony_failed"] = True
            elif row["event_type"] in ("disposition.set",
                                       "disposition.override"):
                call["disposition_events"].append({
                    "event_type": row["event_type"],
                    "occurred_at": occurred,
                    "disposition_code": row["disposition_code"],
                })
        # keep only calls with an initiated event
        calls = {cid: c for cid, c in calls.items()
                 if c["initiated_at"] is not None}
        for call in calls.values():
            call["effective_disposition"] = _effective_disposition(
                call["disposition_events"])

        def is_terminal(workflow_id, code):
            if code is None:
                return False
            return dispositions.get((workflow_id, code), (False, False))[0]

        def is_success(workflow_id, code):
            if code is None:
                return False
            return dispositions.get((workflow_id, code), (False, False))[1]

        # calls per lead
        calls_by_lead = {}
        for cid, call in calls.items():
            key = (call["workflow_id"], call["phone_hash"])
            calls_by_lead.setdefault(key, []).append((cid, call))

        # ---- per-lead derived facts ----
        lead_facts = {}
        for lead in leads:
            key = (lead["workflow_id"], lead["phone_hash"])
            lead_calls = calls_by_lead.get(key, [])
            call_summaries = [{
                "has_telephony_failed": c["telephony_failed"],
                "effective_disposition": c["effective_disposition"],
            } for _, c in lead_calls]
            bucket = _bucket(
                call_summaries,
                lambda code, wf=lead["workflow_id"]: is_terminal(wf, code))
            connected = sum(1 for _, c in lead_calls if c["connected"])
            last_call = max((c["initiated_at"] for _, c in lead_calls),
                            default=None)
            recent_with_disp = [
                c for _, c in sorted(
                    lead_calls, key=lambda x: x[1]["initiated_at"])
                if c["effective_disposition"] is not None]
            current_disp = (recent_with_disp[-1]["effective_disposition"]
                            if recent_with_disp else "")
            ever_success = any(
                is_success(lead["workflow_id"], c["effective_disposition"])
                for _, c in lead_calls)
            lead_facts[key] = {
                "bucket": bucket,
                "total_calls": len(lead_calls),
                "connected_calls": connected,
                "last_call_at": ist_iso(last_call) if last_call else "",
                "current_disposition": current_disp,
                "ever_success": ever_success,
            }

        os.makedirs(out_dir, exist_ok=True)

        # ---- 1. batch_summary.csv ----
        batch_rows = {}
        for lead in leads:
            key = (lead["workflow_id"], lead["batch_id"])
            row = batch_rows.setdefault(key, {
                "workflow_id": lead["workflow_id"],
                "batch_id": lead["batch_id"],
                "total_leads": 0, "yet_to_reach_out": 0,
                "in_progress_telephony_failed": 0, "in_progress_dialed": 0,
                "completed": 0})
            row["total_leads"] += 1
            row[lead_facts[(lead["workflow_id"],
                            lead["phone_hash"])]["bucket"]] += 1
        with open(os.path.join(out_dir, "batch_summary.csv"), "w",
                  newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["workflow_id", "batch_id", "total_leads",
                        "yet_to_reach_out", "in_progress_telephony_failed",
                        "in_progress_dialed", "completed"])
            for key in sorted(batch_rows):
                r = batch_rows[key]
                w.writerow([r["workflow_id"], r["batch_id"],
                            r["total_leads"], r["yet_to_reach_out"],
                            r["in_progress_telephony_failed"],
                            r["in_progress_dialed"], r["completed"]])

        # ---- 2. daily_overview.csv ----
        daily = {}
        for cid, call in calls.items():
            key = (call["workflow_id"], ist_date(call["initiated_at"]))
            row = daily.setdefault(key, {
                "workflow_id": call["workflow_id"],
                "date": ist_date(call["initiated_at"]).isoformat(),
                "total_calls": 0, "connected_calls": 0,
                "success_leads": set()})
            row["total_calls"] += 1
            if call["connected"]:
                row["connected_calls"] += 1
            if is_success(call["workflow_id"],
                          call["effective_disposition"]):
                row["success_leads"].add(
                    (call["workflow_id"], call["phone_hash"]))
        with open(os.path.join(out_dir, "daily_overview.csv"), "w",
                  newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["workflow_id", "date", "total_calls",
                        "connected_calls", "connectivity_rate",
                        "success_leads"])
            for key in sorted(daily):
                r = daily[key]
                rate = (r["connected_calls"] / r["total_calls"]
                        if r["total_calls"] else 0.0)
                w.writerow([r["workflow_id"], r["date"], r["total_calls"],
                            r["connected_calls"], f"{rate:.4f}",
                            len(r["success_leads"])])

        # ---- 3. lead_report.csv ----
        with open(os.path.join(out_dir, "lead_report.csv"), "w",
                  newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["workflow_id", "external_ref", "batch_id",
                        "phone_masked", "bucket", "total_calls",
                        "connected_calls", "last_call_at",
                        "current_disposition", "ever_success"])
            for lead in sorted(leads, key=lambda l: (l["workflow_id"],
                                                     l["external_ref"])):
                facts = lead_facts[(lead["workflow_id"],
                                    lead["phone_hash"])]
                w.writerow([lead["workflow_id"], lead["external_ref"],
                            lead["batch_id"], lead["phone_masked"],
                            facts["bucket"], facts["total_calls"],
                            facts["connected_calls"], facts["last_call_at"],
                            facts["current_disposition"],
                            "true" if facts["ever_success"] else "false"])

        # ---- 4. rejections.csv (no PII) ----
        with open(os.path.join(out_dir, "rejections.csv"), "w",
                  newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["workflow_id", "batch_id", "row_number", "reason"])
            for row in conn.execute(
                    "SELECT workflow_id, batch_id, row_number, reason "
                    "FROM rejections ORDER BY workflow_id, batch_id, "
                    "row_number"):
                w.writerow([row["workflow_id"], row["batch_id"],
                            row["row_number"], row["reason"]])

        # ---- 5. data_quality.json ----
        counters = db.get_counters(conn)
        rejections_by_reason = {}
        for row in conn.execute(
                "SELECT reason, COUNT(*) AS n FROM rejections "
                "GROUP BY reason"):
            rejections_by_reason[row["reason"]] = row["n"]
        orphan_events = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE linked = 0"
            ).fetchone()["n"]
        quality = {
            "lead_rows_total": counters["lead_rows_total"],
            "lead_rows_rejected": counters["lead_rows_rejected"],
            "rejections_by_reason": rejections_by_reason,
            "duplicate_lead_rows_merged":
                counters["duplicate_lead_rows_merged"],
            "field_warnings": counters["field_warnings"],
            "events_total": counters["events_total"],
            "malformed_events": counters["malformed_events"],
            "duplicate_events_dropped":
                counters["duplicate_events_dropped"],
            "orphan_events": orphan_events,
            "unknown_disposition_events":
                counters["unknown_disposition_events"],
        }
        with open(os.path.join(out_dir, "data_quality.json"), "w",
                  encoding="utf-8") as f:
            json.dump(quality, f, indent=2)
            f.write("\n")
    finally:
        conn.close()
