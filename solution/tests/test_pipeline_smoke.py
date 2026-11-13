"""End-to-end smoke tests — these should PASS.

They build a tiny drop in a temp dir (no generated data needed), run
ingest twice and report once, and check the pipeline holds together:
five files exist, headers are exact, re-ingest changes nothing.
"""
import csv
import json
import os

from solution import db
from solution.ingest import ingest_drop
from solution.report import build_reports


def _tiny_drop(tmp_path):
    drop = tmp_path / "drop_1"
    leads_dir = drop / "leads" / "motor_renewal"
    leads_dir.mkdir(parents=True)
    with open(leads_dir / "batch_001.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_name", "phone", "policy_number",
                    "policy_expiry", "premium_amount",
                    "preferred_language"])
        w.writerow(["Aarav Sharma", "+91 98765 43210", "MOT/2026/000001",
                    "01-Dec-2026", "₹12,000", "ta"])
        w.writerow(["", "", "", "", "", ""])  # blank row: skipped
        w.writerow(["Bad Phone", "12345", "MOT/2026/000002",
                    "", "", ""])  # invalid phone -> rejection
    events_dir = drop / "events"
    events_dir.mkdir()
    events = [
        {"event_id": "evt_1", "event_type": "call.initiated",
         "workflow_id": "motor_renewal", "call_id": "call_1",
         "occurred_at": "2026-10-05T13:20:21Z", "phone": "+919876543210",
         "payload": {}},
        {"event_id": "evt_2", "event_type": "call.connected",
         "workflow_id": "motor_renewal", "call_id": "call_1",
         "occurred_at": "2026-10-05T13:20:30Z", "phone": "+919876543210",
         "payload": {}},
        {"event_id": "evt_3", "event_type": "disposition.set",
         "workflow_id": "motor_renewal", "call_id": "call_1",
         "occurred_at": "2026-10-05T13:22:00Z", "phone": "+919876543210",
         "payload": {"disposition_code": "renewed"}},
        {"event_id": "evt_1", "event_type": "call.initiated",  # duplicate
         "workflow_id": "motor_renewal", "call_id": "call_1",
         "occurred_at": "2026-10-05T13:20:21Z", "phone": "+919876543210",
         "payload": {}},
        "{not json",  # malformed
    ]
    with open(events_dir / "events_0001.jsonl", "w") as f:
        for e in events:
            f.write(e if isinstance(e, str) else json.dumps(e))
            f.write("\n")
    return str(drop)


def test_end_to_end_produces_five_files(tmp_path):
    drop = _tiny_drop(tmp_path)
    db_path = str(tmp_path / "ledger.db")
    out = str(tmp_path / "reports")
    ingest_drop(db_path, drop)
    build_reports(db_path, out)
    for name in ("batch_summary.csv", "daily_overview.csv",
                 "lead_report.csv", "rejections.csv", "data_quality.json"):
        assert os.path.exists(os.path.join(out, name)), f"missing {name}"
    with open(os.path.join(out, "batch_summary.csv")) as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["workflow_id"] == "motor_renewal"
    assert rows[0]["batch_id"] == "batch_001"
    assert rows[0]["total_leads"] == "1"
    with open(os.path.join(out, "rejections.csv")) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1 and rows[0]["reason"] == "invalid_phone"
    with open(os.path.join(out, "data_quality.json")) as f:
        quality = json.load(f)
    assert quality["lead_rows_total"] == 2
    assert quality["lead_rows_rejected"] == 1
    assert quality["events_total"] == 5
    assert quality["malformed_events"] == 1
    assert quality["duplicate_events_dropped"] == 1
    assert quality["orphan_events"] == 0
    with open(os.path.join(out, "daily_overview.csv")) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["total_calls"] == "1"
    assert rows[0]["connected_calls"] == "1"
    assert rows[0]["connectivity_rate"] == "1.0000"
    assert rows[0]["success_leads"] == "1"


def test_lead_report_masks_phone_and_no_plaintext_pii(tmp_path):
    drop = _tiny_drop(tmp_path)
    db_path = str(tmp_path / "ledger.db")
    out = str(tmp_path / "reports")
    ingest_drop(db_path, drop)
    build_reports(db_path, out)
    with open(os.path.join(out, "lead_report.csv")) as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["phone_masked"] == "+91******3210"
    assert rows[0]["current_disposition"] == "renewed"
    assert rows[0]["ever_success"] == "true"
    # no plaintext PII anywhere in the DB dump or reports
    conn = db.connect(db_path)
    dump = "\n".join(
        str(r) for r in conn.execute("SELECT * FROM leads"))
    assert "9876543210" not in dump
    assert "Aarav Sharma" not in dump


def test_reingest_is_noop(tmp_path):
    drop = _tiny_drop(tmp_path)
    db_path = str(tmp_path / "ledger.db")
    out1 = str(tmp_path / "reports1")
    out2 = str(tmp_path / "reports2")
    ingest_drop(db_path, drop)
    build_reports(db_path, out1)
    ingest_drop(db_path, drop)
    build_reports(db_path, out2)
    for name in ("batch_summary.csv", "daily_overview.csv",
                 "lead_report.csv", "rejections.csv", "data_quality.json"):
        with open(os.path.join(out1, name), "rb") as f:
            first = f.read()
        with open(os.path.join(out2, name), "rb") as f:
            second = f.read()
        assert first == second, f"{name} changed on re-ingest"
