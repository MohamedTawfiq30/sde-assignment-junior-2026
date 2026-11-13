# Assignment A — Interaction Ledger & Reporting Pipeline

The mechanical parts plus all five assessed rules are implemented (see
below). You must be able to walk through every line of this code and
defend it in the 45-minute follow-up — read it before you run it.

## Setup (from a clean clone)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r solution/requirements.txt   # pytest only; runtime is stdlib
```

## Generate the data

```bash
python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
# The graders will run your pipeline on a DIFFERENT seed. Never commit
# generated data (data/ is gitignored).
```

## Run the pipeline

```bash
python -m solution.pipeline ingest data/drop_1
python -m solution.pipeline ingest data/drop_2
python -m solution.pipeline report --out reports/
```

Re-running `ingest` on a drop you already ingested changes nothing
(files are recorded in `ingest_state`). The ledger is SQLite at
`solution/ledger.db` (gitignored). Delete it to start over.

## What is implemented

| Piece | File | Status |
|---|---|---|
| CLI (`ingest` / `report`) | `solution/pipeline.py` | Done |
| Header normalisation, phone/date/decimal/enum parsing, event timestamps | `solution/normalize.py` | Done + tested |
| PII: salted SHA-256 phone/name hashes, masked phones | `solution/pii.py` | Done + tested |
| SQLite schema: leads, append-only events ledger, rejections, ingest_state, counters | `solution/db.py` | Done |
| Lead validation (schema order, first-failure rejection, field warnings), duplicate detection, event dedupe/malformed/unknown-disposition handling, orphan quarantine + re-link retry | `solution/ingest.py` | Done (calls `rules.py` directly) |
| The five report files, exact columns/sorts, 4-decimal connectivity rate, ISO-8601 IST `last_call_at` | `solution/report.py` | Done (derived facts via `rules.py`) |
| The five core rules: merge, link, relink, effective disposition, bucket | `solution/rules.py` | Done + tested (see below) |

## The five core rules — implemented in `solution/rules.py`

Each function has a docstring quoting the spec, a one-line defence
summary, and passing tests in `tests/test_todo_rules.py`:

1. **`merge_duplicate`** — first valid row creates the lead (its
   `batch_id` is permanent); later rows overwrite only non-null fields;
   defaults apply after merging (applied in `report.py` when leads are
   loaded — the only defaulted field is `preferred_language`, and no
   report column reads it).
2. **`link_event`** — link by (workflow, normalised phone); a
   `disposition.override` links via its `call_id` only.
3. **`relink_orphans`** — events that arrived before their lead must
   count once the lead arrives in a later drop; orphan counts in
   `data_quality.json` reflect the final state. The caller repeats to a
   fixpoint, because an override can only link once its call's other
   events are linked.
4. **`effective_disposition`** — latest override by `occurred_at`, else
   latest set, else none. Overrides never edit the original event.
5. **`bucket`** — `yet_to_reach_out` / `completed` /
   `in_progress_telephony_failed` / `in_progress_dialed`, first match
   wins.

The old `baseline.py` fallbacks (deliberately not spec-correct — they
ignored overrides and the telephony-failed bucket) have been deleted
along with their call sites.

Idempotent re-ingest is implemented (file-level `ingest_state`) and
covered by a passing smoke test — see `tests/test_pipeline_smoke.py`.

## Tests

```bash
python -m pytest solution/tests -v
```

Expected: all tests pass, including the five rule tests in
`tests/test_todo_rules.py`.

## Honesty notes (yours to fill)

- **`AI_USAGE.md`** (repo root) — fill it in honestly: this starter
  was scaffolded with AI assistance. Say what the AI wrote, what you
  wrote/decided yourself, where the AI was wrong, and how you verified
  the code. Discovering undisclosed use is held against you; honest
  disclosure is not.
- **`SUBMISSION.md`** (repo root) — fill in the template: design,
  decisions & assumptions (every place you made a call the spec didn't
  make), failure modes, testing, results, and what you'd do with
  another day.
- **Submit via the Microsoft Forms link from the acceptance email**
  (`https://forms.cloud.microsoft/r/bc9xAMYdtV`), NOT the README's
  `[[SUBMISSION_EMAIL]]` placeholder — the README submission section
  still has unfilled placeholders. Deadline: **Fri 13 Nov EOD**.
  Push your work to a **private** repo; do not publish the solution
  publicly, and do not commit generated data, `.env` files, or
  databases.

## PII salt

The phone/name hash salt comes from the `AGENTIC_PII_SALT` environment
variable; the default (`dev-salt-change-me`) is for local development
only. If you change the salt between runs, previously stored hashes
will no longer match — delete `solution/ledger.db` and re-ingest.
