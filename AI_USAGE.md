# AI Usage Disclosure

> DRAFT prepared 13 Nov 2026 — Tawfi, read this, fix anything that is not true,
> and rewrite it in your own words before you submit. Every fact here must be
> one you can stand behind in the follow-up call.

AI tools are allowed. We want to know **how** you used them, because using them well is a
skill. Honest answers are never held against you. Discovering undisclosed use is.

## Tools used

Muse — Meta's personal AI assistant (Muse Spark model), used in a chat session
on 12–13 Nov 2026.

## What I used them for

- Scaffolded the whole pipeline: the CLI, phone/date/decimal normalisers, PII
  hashing, the SQLite schema, the ingest code and the five report writers.
- Implemented the five core rules in `solution/rules.py` (merge, link, relink,
  effective disposition, bucket) on 13 Nov, after I chose Assignment A.
- Wrote the test suite (`solution/tests/`) and ran it, plus the end-to-end
  verification run on generated seed-42 data.
- Explained each rule to me in plain words until I could say it back in my own
  words, and wrote the walkthrough notes I used to learn them.

## What I wrote or decided myself

- I chose Assignment A over B: A is deterministic and graded on correctness,
  while B is a distributed system in miniature. I made that call after the
  trade-off was explained to me.
- I directed the work: I asked for the task to be completed, checked the
  results (29/29 tests, the five report files, the re-ingest check), and asked
  for plain-words explanations of every rule before accepting it.
- I decided the submission route: private repo, submit through the Forms link
  from the acceptance email, not the README's placeholder.

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
