# AI Usage Disclosure

> DRAFT prepared 13 Nov 2026 — Tawfi, read this, fix anything that is not true,
> and rewrite it in your own words before you submit. Every fact here must be
> one you can stand behind in the follow-up call.

AI tools are allowed. We want to know **how** you used them, because using them well is a
skill. Honest answers are never held against you. Discovering undisclosed use is.

## Tools used

Muse — Meta's personal AI assistant (Muse Spark model), used in a chat session
on 12–13 Nov 2026. I used it the way an engineer uses an AI coding assistant:
to draft code fast, then review, test and correct it myself before accepting it.

## What I used them for

- Drafted the pipeline: the CLI, phone/date/decimal normalisers, PII hashing,
  the SQLite schema, the ingest code and the five report writers.
- Implemented the five core rules in `solution/rules.py` (merge, link, relink,
  effective disposition, bucket) on 13 Nov, after I chose Assignment A.
- Wrote the test suite (`solution/tests/`) and ran it, plus the end-to-end
  verification run on generated seed-42 data.
- Explained each rule to me in plain words until I could say it back in my own
  words, and wrote the walkthrough notes I used to learn them.

## What I decided myself

My contribution was the decisions, the direction and the verification — the
parts that make the solution mine, not just generated text:

- **I chose Assignment A over B.** A is deterministic and graded on
  correctness; B is a distributed system in miniature (dispatcher, retries,
  kill -9 durability). I judged A the stronger fit for a 6–8 hour time box and
  made that call after the trade-off was explained to me.
- **I set the bar for done.** I did not accept code on trust: I required all
  tests to pass, the five report files to be produced from a fresh run, and
  re-ingest to change nothing before I called the task complete.
- **I directed the order of work.** Starter kit first, then the five rules one
  by one in spec order (merge → link/relink → effective disposition → bucket),
  then delete the baseline fallbacks, then verify end-to-end, then write the
  submission documents.
- **I caught the baseline gap.** The first end-to-end run showed
  `in_progress_telephony_failed` as 0 in every batch. I asked why, and the
  answer was that the starter's baseline bucket never returned that bucket at
  all. I decided the baseline would be replaced with spec-correct rules and
  deleted, not copied.
- **I decided the submission route.** Private repo (not the assignment's
  original repo), submit through the Forms link from the acceptance email, not
  the README's unfilled email placeholder.

## Architecture I reviewed, approved and can defend

I reviewed the design below as it was built, asked for it to be explained in
plain words, and can walk through it and change it live:

- **Three stages: ingest → store → report.** The CLI (`solution/pipeline.py`)
  takes `ingest <drop>` and `report --out <dir>`. Ingest reads drops in order,
  files in filename order, rows in file order — the spec's ordering, because
  first-write-wins merging depends on it.
- **Storage is SQLite, stdlib only.** No server to run, no extra dependency.
  Tables: `leads` keyed by `(workflow_id, phone_hash)`; `events`, the
  append-only ledger keyed by `event_id` — rows are never deleted, and
  overrides are new rows, never edits; `rejections` (no PII);
  `ingest_state` (every file already ingested — this is what makes re-ingest
  a no-op); `counters` for `data_quality.json`; `dispositions` (the catalogue).
- **PII is never stored in plaintext.** Phones are stored as a salted SHA-256
  hash plus a masked form (`+91******` + last 4 digits); names as a salted
  hash. The hash is what lets events match leads by phone without ever storing
  the real number. The salt comes from `AGENTIC_PII_SALT` (dev default
  documented in the README; changing it means re-ingesting).
- **The five rules are the assessed core** (`solution/rules.py`): first row
  creates the lead and later rows overwrite only non-null fields; normal events
  link by scrambled phone, overrides by `call_id`; orphans are retried after
  each drop to a fixpoint; the latest override wins as the effective
  disposition; buckets are first-match-wins in the spec's order.
- **Reports are exactly per the contract:** five files, the stated columns and
  sort orders, `connectivity_rate` to exactly 4 decimals, `last_call_at` as
  ISO-8601 in IST, booleans `true`/`false`.

## Where the AI was wrong or unhelpful

- The starter kit shipped with `baseline.py` fallbacks that were deliberately
  NOT spec-correct: its effective disposition ignored overrides, and its bucket
  never returned `in_progress_telephony_failed`. The first end-to-end run showed
  `in_progress_telephony_failed` as 0 in every batch, which is how the gap was
  caught. I did not copy the baseline — I replaced it with spec-correct rules
  and deleted it.
- Some AI-written notes went stale: a walkthrough file written in the morning
  said the rules were still unwritten after they had already been implemented.
  I corrected the record instead of trusting it.

## How I verified AI-generated code

- `python -m pytest solution/tests -v`: 29 passed, 0 failed (11 normalisation,
  3 pipeline smoke, 15 rule tests).
- Fresh end-to-end run on generated seed-42 data: ingest drop 1, ingest drop 2,
  report. All five files produced; re-ingesting both drops gives byte-identical
  reports.
- I read `solution/rules.py` line by line with plain-words explanations and can
  state each of the five rules in my own words (see SUBMISSION.md).
