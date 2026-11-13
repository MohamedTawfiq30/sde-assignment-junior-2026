"""TODO-rule tests — these are EXPECTED TO FAIL right now.

Each test defines one core rule from the spec (see ``solution/rules.py``
docstrings). The rule functions are stubs raising ``NotImplementedError``,
so every test below fails until you implement the rule. That is the
point: make them pass one by one, in this order:

    1. merge_duplicate
    2. link_event + relink_orphans
    3. effective_disposition
    4. bucket

The one exception is ``test_idempotent_reingest``: idempotency is
already implemented (file-level ``ingest_state`` in ``db.py``), so that
test passes today and guards the behaviour. It is kept in this file
because the spec lists idempotent re-ingest among the core rules.
"""
from datetime import datetime, timezone

import pytest

from solution import rules

UTC = timezone.utc


def _ev(etype, when, code=None):
    return {"event_type": etype,
            "occurred_at": datetime.fromisoformat(when).replace(tzinfo=UTC),
            "payload": {"disposition_code": code} if code else {}}


# ---------------------------------------------------------------- merge
def test_merge_duplicate_overwrites_only_non_null_fields():
    existing = {"policy_number": "MOT/2026/000001",
                "premium_amount": 12000.0, "preferred_language": "ta"}
    new = {"policy_number": "MOT/2026/000001",
           "premium_amount": None, "preferred_language": "hi"}
    merged = rules.merge_duplicate(existing, new)
    assert merged["premium_amount"] == 12000.0   # null does not overwrite
    assert merged["preferred_language"] == "hi"  # last write wins


def test_merge_duplicate_keeps_first_batch_id():
    # The rule lives in ingest.py (batch_id is permanent), but the
    # merge itself must never touch identity fields. A merged dict must
    # not invent a batch_id.
    merged = rules.merge_duplicate({"premium_amount": 100.0},
                                   {"premium_amount": 200.0})
    assert merged["premium_amount"] == 200.0
    assert "batch_id" not in merged


# ---------------------------------------------------------------- link
def test_link_event_by_phone():
    event = {"event_type": "call.initiated", "call_id": "call_1"}
    assert rules.link_event(event, "hash-abc",
                            lambda h: h == "hash-abc",
                            lambda cid: None) == "hash-abc"


def test_link_event_orphan_when_no_lead():
    event = {"event_type": "call.initiated", "call_id": "call_1"}
    assert rules.link_event(event, "hash-abc",
                            lambda h: False,
                            lambda cid: None) is None


def test_link_event_override_links_via_call_id_only():
    # Overrides carry no phone — they link through call_id alone.
    event = {"event_type": "disposition.override", "call_id": "call_9"}
    assert rules.link_event(event, None,
                            lambda h: False,
                            lambda cid: "hash-lead" if cid == "call_9"
                            else None) == "hash-lead"


def test_link_event_override_with_no_matching_call_is_orphan():
    event = {"event_type": "disposition.override", "call_id": "call_zzz"}
    assert rules.link_event(event, None,
                            lambda h: False,
                            lambda cid: None) is None


def test_relink_orphans_after_lead_arrives():
    orphans = [
        {"event_id": "evt_1", "event_type": "call.initiated",
         "workflow_id": "motor_renewal", "call_id": "call_1",
         "phone_hash": "hash-abc"},
        {"event_id": "evt_2", "event_type": "call.initiated",
         "workflow_id": "motor_renewal", "call_id": "call_2",
         "phone_hash": "hash-still-missing"},
    ]
    linked = rules.relink_orphans(
        orphans,
        lambda o: o["phone_hash"] if o["phone_hash"] == "hash-abc" else None)
    assert linked == {"evt_1": "hash-abc"}  # evt_2 stays an orphan


# ------------------------------------------------- effective disposition
def test_effective_disposition_latest_set():
    events = [
        _ev("disposition.set", "2026-10-05T10:00:00", "callback_requested"),
        _ev("disposition.set", "2026-10-05T11:00:00", "renewed"),
    ]
    assert rules.effective_disposition(events) == "renewed"


def test_effective_disposition_latest_override_wins():
    events = [
        _ev("disposition.set", "2026-10-05T10:00:00", "renewed"),
        _ev("disposition.override", "2026-10-06T09:00:00",
            "not_interested"),
        _ev("disposition.set", "2026-10-06T10:00:00", "callback_requested"),
    ]
    # The override is later than the first set but earlier than the
    # second set — latest OVERRIDE wins regardless of later sets.
    assert rules.effective_disposition(events) == "not_interested"


def test_effective_disposition_none_when_no_disposition():
    events = [_ev("call.initiated", "2026-10-05T10:00:00"),
              _ev("call.connected", "2026-10-05T10:00:10")]
    assert rules.effective_disposition(events) is None


# ---------------------------------------------------------------- bucket
def test_bucket_yet_to_reach_out():
    assert rules.bucket([], lambda code: False) == "yet_to_reach_out"


def test_bucket_completed_when_any_call_terminal():
    calls = [
        {"has_telephony_failed": False, "effective_disposition": "renewed"},
        {"has_telephony_failed": True, "effective_disposition": None},
    ]
    assert rules.bucket(
        calls, lambda code: code == "renewed") == "completed"


def test_bucket_telephony_failed_when_every_call_failed():
    calls = [
        {"has_telephony_failed": True, "effective_disposition": None},
        {"has_telephony_failed": True, "effective_disposition": None},
    ]
    assert rules.bucket(
        calls, lambda code: False) == "in_progress_telephony_failed"


def test_bucket_dialed_otherwise():
    calls = [
        {"has_telephony_failed": True, "effective_disposition": None},
        {"has_telephony_failed": False,
         "effective_disposition": "callback_requested"},
    ]
    assert rules.bucket(
        calls, lambda code: False) == "in_progress_dialed"


# ------------------------------------------------------------ idempotency
def test_idempotent_reingest(tmp_path, monkeypatch):
    """Already implemented via ingest_state — this test PASSES today.

    It is here because the spec lists idempotent re-ingest among the
    core rules. It guards the behaviour: ingesting the same drop twice
    must not change any counter or table.
    """
    import csv
    import json as _json

    from solution import db
    from solution.ingest import ingest_drop

    drop = tmp_path / "drop_1"
    leads_dir = drop / "leads" / "motor_renewal"
    leads_dir.mkdir(parents=True)
    (leads_dir / "batch_001.csv").write_text(
        "customer_name,phone,policy_number\n"
        "Aarav Sharma,+919876543210,MOT/2026/000001\n")
    events_dir = drop / "events"
    events_dir.mkdir()
    (events_dir / "events_0001.jsonl").write_text(
        _json.dumps({"event_id": "evt_1", "event_type": "call.initiated",
                     "workflow_id": "motor_renewal", "call_id": "call_1",
                     "occurred_at": "2026-10-05T13:20:21Z",
                     "phone": "+919876543210", "payload": {}}) + "\n")
    db_path = str(tmp_path / "ledger.db")
    ingest_drop(db_path, str(drop))
    before = db.get_counters(db.connect(db_path))
    n_leads = db.connect(db_path).execute(
        "SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    ingest_drop(db_path, str(drop))  # second run must be a no-op
    after = db.get_counters(db.connect(db_path))
    n_leads_after = db.connect(db_path).execute(
        "SELECT COUNT(*) AS n FROM leads").fetchone()["n"]
    assert before == after
    assert n_leads == n_leads_after == 1
