# Submission

> DRAFT prepared 13 Nov 2026 — Tawfi, read this, fix anything that is not true,
> and rewrite it in your own words before you submit. The reviewers read every
> word and will ask you about it in the follow-up call.

## Candidate

- **Name:** Mohamed Tawfiq J
- **Assignment chosen:** A (Data) — Interaction Ledger & Reporting Pipeline
- **Time spent (honest estimate):** [fill in your real hours — the work ran across 12–13 Nov 2026, including learning the spec]

## How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r solution/requirements.txt   # pytest only; runtime is stdlib
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
python -m solution.pipeline ingest data/drop_1
python -m solution.pipeline ingest data/drop_2
python -m solution.pipeline report --out reports/
python -m pytest solution/tests -v
```

The ledger is SQLite at `solution/ledger.db` (gitignored). Delete it to start over.
Re-running `ingest` on a drop you already ingested changes nothing.

## Design

A small command-line pipeline in three stages: **ingest → store → report**.

- **Ingest** (`solution/ingest.py`, `solution/normalize.py`): lead CSVs are read in
  drop order, filename order, row order. Headers are normalised and matched
  against the schema (name or aliases); unknown columns are ignored; blank rows
  are skipped and not counted. Fields are validated in schema order and the
  first failure is the row's single rejection reason (`missing_required:<field>`
  or `invalid_phone`). Optional fields that are present but invalid become null
  and count one field warning. Duplicates (same workflow + canonical phone)
  merge: later rows overwrite only non-null fields, and `batch_id` stays the
  first row's batch forever. Event JSONL lines are checked in order: malformed,
  then duplicate `event_id`, then unknown disposition code, then linked to a
  lead or quarantined as an orphan.
- **Store** (`solution/db.py`): SQLite, stdlib only. Tables: `leads` keyed by
  `(workflow_id, phone_hash)`; `events`, the append-only ledger, keyed by
  `event_id` — rows are never deleted and never edited, except the `linked` /
  `phone_hash` flags when an orphan is re-linked, and overrides are new rows,
  never edits; `rejections` (no PII); `ingest_state` (every file already
  ingested, which is what makes re-ingest a no-op); `counters` for
  `data_quality.json`; `dispositions` (the catalogue). PII is never stored in
  plaintext: phones are stored as a salted SHA-256 hash plus a masked form
  (`+91******` + last 4 digits), names as a salted hash, and `fields_json`
  holds only non-PII fields. The salt comes from `AGENTIC_PII_SALT`
  (dev default documented in the README; changing it means re-ingesting).
- **Report** (`solution/report.py`): the five files, exactly per the output
  contract — header row, `,` delimiter, `\n` endings, booleans `true`/`false`,
  the stated sort orders, `connectivity_rate` to exactly 4 decimals, and
  `last_call_at` as ISO-8601 in IST. A call counts only if its `call.initiated`
  event is present and linked; its date is the IST date of `call.initiated`.
- **Rules** (`solution/rules.py`): the five assessed decisions, each with a
  spec-quoting docstring and a one-line defence. Merge: first row creates the
  lead, later rows overwrite only non-null fields. Link: normal events by
  scrambled phone; overrides (no phone) by `call_id`. Relink: retry orphans
  after each drop, to a fixpoint, because an override can only link once its
  call's other events are linked. Effective disposition: latest override by
  time wins, else latest set, else none. Bucket: first match wins — no calls,
  any terminal call, every call telephony-failed, otherwise dialled.

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| Defaults (e.g. `preferred_language → en`) applied when leads are loaded in `report.py`, not at ingest time | The only defaulted field is `preferred_language`, and no report column reads it, so the result is identical; the stored row keeps the true null | Apply at ingest time in `apply_defaults` (kept as a helper, unused) |
| Orphan re-link runs to a fixpoint (up to 10 passes) after each drop | An override can only link once its call's `call.initiated` event has linked first, so one pass can leave it stranded | Single pass (would under-count overrides that arrive before their call's other events) |
| PII salt from an env var with a documented dev default | Lets the graders run it with no setup; changing the salt is an explicit re-ingest | A fixed salt in code (worse: looks like a secret, and can't be rotated) |
| Report aggregation in Python, not SQL | Clearer to read and to defend line by line; the dataset is small | SQL aggregation (a listed stretch goal — see "If I had another day") |
| No stretch goals attempted | The brief says a clean, correct core beats a sprawling half-working stretch | Large-scale timing run, SQL aggregation, production note |

## Failure modes considered

- **Bad input:** malformed JSON lines, missing `event_id`, invalid phones, missing
  required fields, impossible dates, negative amounts — all counted and rejected
  with a reason, never crashing the run. Rejections carry no PII.
- **Duplicates:** duplicate lead rows merge (counted); duplicate `event_id`s
  (including across drops) are counted and skipped.
- **Events before their lead:** kept as orphans, retried after every drop, and
  `orphan_events` in `data_quality.json` reflects the final state.
- **Re-runs:** `ingest_state` records every file; re-ingesting a drop is a
  no-op (verified: byte-identical reports).
- **Overrides:** never edit the original event; the ledger stays append-only.
- **Not handled:** a crash mid-drop can leave a file's rows committed but its
  `ingest_state` record uncommitted, so the next run re-processes that file.
  The ledger stays correct (dedupe by `event_id`, leads upsert by identity),
  but counters can be double-counted. Fixing that (one transaction per file,
  state included) is first on my "another day" list.

## Testing

29 tests, all passing (`python -m pytest solution/tests -v`):

- 11 normalisation tests: phone formats and invalid phones, date formats and
  impossible dates, decimal formats, enum case handling, event timestamps
  (UTC, offset, naive = IST).
- 3 pipeline smoke tests: end-to-end run produces all five files; no plaintext
  phone or name leaks into any report; re-ingest is a no-op.
- 15 rule tests in `test_todo_rules.py`: merge (blank never erases, batch_id
  never invented), link (by phone, orphan when no lead, override by call_id
  only, override with no matching call is an orphan), relink (lead arrived →
  links, still missing → stays orphan), effective disposition (latest set,
  latest override beats a later set, none when no disposition), bucket (all
  four branches, including the trap: one failed + one dialled call is dialled,
  not telephony-failed), and idempotent re-ingest.
- Not tested: the `--scale large` dataset (timing stretch goal), and crash
  recovery mid-drop (see above).

## Results

Fresh seed-42 run, small scale (2,057 lead rows, 8,745 event lines), full
ingest + report in a few seconds:

- 1,892 leads; 108 rejected (42 invalid phones, 25 missing names, 13 missing
  order ids, 14 missing phones, 14 missing policy numbers); 57 duplicates
  merged; 122 field warnings.
- 8,745 events: 8 malformed, 235 duplicate events dropped, 21 unknown
  dispositions, 461 orphans (events for numbers never uploaded, or whose lead
  never arrived).
- Surprising: the telephony-failed bucket was 0 in every batch under the
  starter's baseline fallback — that is how I caught that the baseline ignored
  it. With the real rule it is 5–9 per batch.

## If I had another day

1. One transaction per file (rows + `ingest_state` together) so a crash mid-drop
   can't double-count counters.
2. Time the `--scale large` dataset and report it; profile the slowest step.
3. Move report aggregation into SQL and compare timings.
4. A short production note: scheduling, backfills, and how to run this for
   100k leads/day.
