"""CORE RULES — implemented. These are the assessed decisions of Assignment A.

Each function below implements one rule from the spec (its docstring
quotes the rule). ``tests/test_todo_rules.py`` defines the expected
behaviour. The baseline fallbacks in ``baseline.py`` have been deleted:
the pipeline now calls these rules directly.

How to defend each rule in the 45-minute follow-up (one line each):
- merge_duplicate: first row creates the lead; later rows overwrite
  only fields where they have a real (non-null) value; batch_id never
  changes.
- link_event: a normal event links by its phone hash; an override has
  no phone, so it links through its call_id to the lead of that call's
  other events. No match = orphan.
- relink_orphans: after each drop, retry every orphan with the same
  linking rule; the caller repeats to a fixpoint because an override
  can only link once its call's other events are linked.
- effective_disposition: latest override by time wins; if there is no
  override, the latest set wins; otherwise none. Overrides never edit
  the original event — the ledger stays append-only.
- bucket: first match wins, in order: no calls, any terminal call,
  every call telephony-failed, otherwise dialled.
"""
from __future__ import annotations


def merge_duplicate(existing: dict, new: dict) -> dict:
    """Duplicate merging.

    Spec: "Lead identity is (workflow_id, canonical phone). Duplicates:
    process drops in the order ingested, files in filename order and rows
    in file order. The first valid row for an identity creates the lead,
    and its file stem (``batch_001``) becomes the lead's ``batch_id``
    permanently. Each later valid row for the same identity counts as one
    merged duplicate and overwrites only the fields where its value is
    non-null (last write wins)."

    ``existing`` and ``new`` are the stored (non-PII) field dicts of the
    lead, e.g. ``{"policy_number": ..., "premium_amount": ...}``.
    Return the merged field dict. The caller's ``batch_id`` must NOT
    change — it stays the first row's batch forever.

    Defaults (for example ``preferred_language → en``) apply after
    merging, to fields that are still null. That happens in
    ``report.build_reports`` when leads are loaded: the only defaulted
    field is ``preferred_language``, and no report column reads it, so
    applying it at report time is equivalent to applying it at ingest
    time. Documented here and in SUBMISSION.md.
    """
    merged = dict(existing)
    for key, value in new.items():
        if value is not None:
            merged[key] = value
    return merged


def link_event(event: dict, phone_hash, lead_exists_by_phone_hash,
               lead_hash_by_call_id):
    """Event linking / orphan handling.

    Spec: "An event links via (workflow_id, normalised phone) using the
    phone rules above. A ``disposition.override`` links through its
    ``call_id`` to the lead of that call's other events." And: "Orphan:
    the event can't be linked to a valid lead → count it and keep it out
    of every report." And: "events can arrive before the lead they belong
    to (in an earlier drop). Reports must always reflect everything
    ingested so far. An event that was an orphan after ``drop_1`` must
    count once its lead arrives in ``drop_2``."

    ``event`` is the parsed JSON dict. ``phone_hash`` is the salted hash
    of the event's normalised phone, or ``None`` if the event has no
    phone (overrides carry no phone — only a ``call_id``). The caller
    computes the hash; this function only decides. ``lead_exists_by_phone_hash``
    is a callable ``(phone_hash) -> bool``; ``lead_hash_by_call_id`` is
    a callable ``(call_id) -> phone_hash | None`` (the lead of another
    event already linked under that call).

    Return the lead's ``phone_hash`` if the event links, else ``None``.
    """
    # Overrides carry no phone — they link through call_id alone.
    if event.get("event_type") == "disposition.override":
        return lead_hash_by_call_id(event.get("call_id"))
    # Normal events link by phone hash, and only if that lead exists.
    if phone_hash is not None and lead_exists_by_phone_hash(phone_hash):
        return phone_hash
    return None


def relink_orphans(orphans: list, link_fn) -> dict:
    """Re-link orphans once their lead arrives.

    Spec: "Orphan counts in ``data_quality.json`` reflect the final
    state." So after every new drop is ingested, previously orphaned
    events must be retried: an event that was an orphan after ``drop_1``
    must count once its lead arrives in ``drop_2``.

    ``orphans`` is a list of small records, one per currently unlinked
    event: ``{"event_id", "event_type", "workflow_id", "call_id",
    "phone_hash"}`` (``phone_hash`` is None for overrides).
    ``link_fn`` is a callable ``(orphan) -> phone_hash | None`` that
    applies the same linking rule as :func:`link_event`.

    Return ``{event_id: phone_hash}`` for the events that now link.
    Events that still don't link stay orphans. One call does one pass;
    the caller (``ingest.relink_orphans``) repeats it to a fixpoint,
    because an override can only link once its call's other events
    are linked.
    """
    linked = {}
    for orphan in orphans:
        hashed = link_fn(orphan)
        if hashed is not None:
            linked[orphan["event_id"]] = hashed
    return linked


def effective_disposition(call_events: list) -> str | None:
    """A call's effective disposition.

    Spec: "A call's effective disposition is the code of its latest
    ``disposition.override`` by ``occurred_at``. If it has no override,
    it's the latest ``disposition.set``. Otherwise it has none.
    Overrides never delete or edit the original event. The ledger stays
    append-only."

    ``call_events`` is a list of event dicts for one call, each with
    ``event_type``, ``occurred_at`` (aware datetime) and a
    ``disposition_code`` inside its ``payload`` (for disposition events).

    Return the disposition code, or ``None`` if the call has none.
    """
    overrides = [e for e in call_events
                 if e.get("event_type") == "disposition.override"]
    if overrides:
        latest = max(overrides, key=lambda e: e["occurred_at"])
        return (latest.get("payload") or {}).get("disposition_code")
    sets = [e for e in call_events
            if e.get("event_type") == "disposition.set"]
    if sets:
        latest = max(sets, key=lambda e: e["occurred_at"])
        return (latest.get("payload") or {}).get("disposition_code")
    return None


def bucket(calls: list, is_terminal) -> str:
    """A lead's bucket.

    Spec: "A lead's bucket is the first of these that matches:
    1. ``yet_to_reach_out``: no calls.
    2. ``completed``: any call's effective disposition is terminal
       (``is_terminal=true``).
    3. ``in_progress_telephony_failed``: every call has a
       ``call.telephony_failed`` event.
    4. ``in_progress_dialed``: everything else."

    ``calls`` is a list of dicts, one per call, each with:
    ``has_telephony_failed`` (bool) and ``effective_disposition``
    (code or None). ``is_terminal`` is a callable
    ``(disposition_code) -> bool`` from the disposition catalogue.

    Return one of the four bucket strings.
    """
    if not calls:
        return "yet_to_reach_out"
    for call in calls:
        code = call.get("effective_disposition")
        if code is not None and is_terminal(code):
            return "completed"
    if all(call.get("has_telephony_failed") for call in calls):
        return "in_progress_telephony_failed"
    return "in_progress_dialed"
