# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""Looks after the MaRTiny MongoDB database.

  python tools/db_admin.py stats                          documents and devices in each collection
  python tools/db_admin.py indexes                        create the indexes the queries rely on (safe to repeat)
  python tools/db_admin.py prune --days 365 [--dry-run]   delete sensor readings and photo results older than N days
  python tools/db_admin.py strip-images --days 7 [--dry-run]
                                                          keep the counts, drop stored photographs and shadow maps older than N days
  python tools/db_admin.py export data --out data.csv     write a collection to .csv or .json

The database is the one in MONGO_URL / MONGO_DB (a .env file works). Add --dry-run to anything that deletes to see what it
would do first. Back up before pruning: mongodump --uri "$MONGO_URL" --out backup/"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from martiny_server.store import READINGS, RESULTS, Store  # noqa: E402


def _cut_s(days: float, now: float) -> int:
    return int(now - days * 86400)


def _flatten(doc: dict) -> dict:
    return {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in doc.items()}


def run(argv, store: Store, out=sys.stdout, now: float = None) -> int:
    now = time.time() if now is None else now
    ap = argparse.ArgumentParser(prog="db_admin", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    sub.add_parser("indexes")
    p = sub.add_parser("prune"); p.add_argument("--days", type=float, required=True); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("strip-images"); p.add_argument("--days", type=float, required=True); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("export"); p.add_argument("collection", choices=[READINGS, RESULTS]); p.add_argument("--out", required=True)
    p.add_argument("--mac"); p.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    if a.cmd == "stats":
        json.dump(store.stats(), out, indent=2, default=str); out.write("\n")
    elif a.cmd == "indexes":
        store.ensure_indexes(); out.write("indexes ready on (mac, time) for both collections\n")
    elif a.cmd == "prune":
        cut = _cut_s(a.days, now)
        done = store.prune(readings_before_ms=cut * 1000, results_before_s=cut, dry_run=a.dry_run)
        out.write(("would delete " if a.dry_run else "deleted ") + json.dumps(done) + "\n")
    elif a.cmd == "strip-images":
        done = store.strip_images(_cut_s(a.days, now), dry_run=a.dry_run)
        out.write(("would remove " if a.dry_run else "removed ") + json.dumps(done) + "\n")
    elif a.cmd == "export":
        flt = {"mac": a.mac} if a.mac else None
        rows = [_flatten(d) for d in store.export(a.collection, flt, a.limit)]
        path = Path(a.out)
        if path.suffix.lower() == ".json":
            path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        else:
            fields = sorted({k for r in rows for k in r}, key=lambda k: (k != "mac", k != "time", k))
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
        out.write(f"wrote {len(rows)} rows to {path}\n")
    return 0


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    url = os.environ.get("MONGO_URL")
    if not url:
        print("Set MONGO_URL (and optionally MONGO_DB) to the database you want to manage.", file=sys.stderr)
        return 2
    from pymongo import MongoClient
    return run(sys.argv[1:], Store(MongoClient(url)[os.environ.get("MONGO_DB", "martiny-studio")]))


if __name__ == "__main__":
    sys.exit(main())
