Submission

Candidate Details

- Name: Mohamed Tawfiq J
- Assignment: A – Data (Interaction Ledger & Reporting Pipeline)
- Time spent: 4-5 hours 

How to Run

python3 -m venv .venv
source .venv/bin/activate
pip install -r solution/requirements.txt

python assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data

python -m solution.pipeline ingest data/drop_1
python -m solution.pipeline ingest data/drop_2

python -m solution.pipeline report --out reports/

python -m pytest solution/tests -v

The application uses SQLite for storage. The database is created at "solution/ledger.db". Re-ingesting an already processed drop does not change the existing data.

Implementation Overview

I built the solution using a simple three-stage architecture:

1. Ingestion

The pipeline reads lead CSV files and event JSONL files in the required order. It validates input data, normalises fields, handles duplicates, and records invalid rows with appropriate rejection reasons.

2. Storage

I used SQLite with Python's standard library. The database maintains leads, events, rejections, ingestion state, counters, and dispositions.

Sensitive information such as phone numbers and names is hashed using salted SHA-256. Plaintext PII is not stored.

3. Reporting

The reporting module generates all five required output files according to the assignment specification, including the expected columns, sorting, date formats, and connectivity calculations.

Core Business Rules

I implemented the five main rules in "solution/rules.py":

1. Lead Merge: New leads are created, and subsequent records update only non-null fields.
2. Event Linking: Events are linked using phone numbers, while override events are linked using "call_id".
3. Orphan Relinking: Unlinked events are retried after each drop until no further events can be linked.
4. Effective Disposition: The latest override takes priority; otherwise, the latest disposition is used.
5. Lead Bucketing: Leads are assigned to buckets based on call history, following the specified rule order.

Important Technical Decisions

- Selected SQLite to keep the application lightweight without requiring an external database server.
- Used environment-based PII salt configuration instead of hardcoding it.
- Used Python for report aggregation to keep the logic readable and easier to maintain.
- Implemented orphan relinking to handle events that arrive before their related records.
- Replaced the starter baseline logic where it did not match the assignment specification.

I prioritised implementing the core requirements correctly instead of spending time on optional stretch goals.

Testing

I ran the test suite using:

python -m pytest solution/tests -v

Result: 29 tests passed, 0 failed.

The tests cover:

- Phone, date, and decimal normalisation.
- Lead merging and event linking.
- Orphan event handling.
- Effective disposition calculation.
- Lead bucket assignment.
- Pipeline execution and report generation.
- PII protection.
- Idempotent ingestion.

I also performed a fresh end-to-end run using the generated seed-42 dataset. All five reports were generated successfully.

I re-ingested both drops and confirmed that the generated reports remained byte-identical.

Results

The small seed-42 dataset contained:

Metric| Result
Lead rows processed| 2,057
Leads created| 1,892
Rejected lead rows| 108
Duplicate leads merged| 57
Field warnings| 122
Events processed| 8,745
Malformed events| 8
Duplicate events| 235
Unknown dispositions| 21
Final orphan events| 461

During testing, I noticed that the starter baseline was not correctly handling the telephony-failed bucket. After investigating, I replaced it with the specification-based implementation. The corrected results showed 5–9 leads in that bucket per batch.

Known Limitations and Future Improvements

If I had more time, I would focus on:

1. Improving crash recovery by handling each file and its ingestion state in a single transaction.
2. Testing performance with the large-scale dataset.
3. Comparing Python-based aggregation with SQL aggregation.
4. Adding production considerations such as scheduling, backfills, and monitoring.

Conclusion

This assignment helped me understand data ingestion, event processing, database design, data validation, and reporting in a practical way.

I used AI as a development assistant, but reviewed the implementation, investigated unexpected results, and verified the final output through automated tests and end-to-end execution.

I can explain the core business rules and the major design decisions made in this implementation.