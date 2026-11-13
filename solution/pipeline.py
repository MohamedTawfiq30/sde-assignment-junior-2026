"""CLI for the Assignment A starter kit.

Usage (from the repo root):

    python -m solution.pipeline ingest data/drop_1
    python -m solution.pipeline ingest data/drop_2
    python -m solution.pipeline report --out reports/

The SQLite ledger lives at ``solution/ledger.db`` by default
(``--db`` overrides it). Re-running ``ingest`` on an already-ingested
drop changes nothing.
"""
from __future__ import annotations

import argparse
import os

from . import db
from .ingest import ingest_drop
from .report import build_reports

DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ledger.db")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="solution.pipeline",
        description="Assignment A: Interaction Ledger & Reporting Pipeline")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help="SQLite ledger path (default: solution/ledger.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest one drop directory")
    p_ingest.add_argument("drop", help="e.g. data/drop_1")

    p_report = sub.add_parser("report", help="Write the five report files")
    p_report.add_argument("--out", required=True,
                          help="Output directory, e.g. reports/")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        ingest_drop(args.db, args.drop)
        counters = db.get_counters(db.connect(args.db))
        print(f"Ingested {args.drop}")
        for key, value in sorted(counters.items()):
            print(f"  {key}: {value}")
    elif args.command == "report":
        build_reports(args.db, args.out)
        print(f"Reports written to {args.out}/")
        for name in ("batch_summary.csv", "daily_overview.csv",
                     "lead_report.csv", "rejections.csv",
                     "data_quality.json"):
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
