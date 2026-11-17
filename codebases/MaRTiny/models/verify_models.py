# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""Checks that the model files you have match the ones the lab runs (size and SHA-256).

  python models/verify_models.py              look in this folder
  python models/verify_models.py --dir /data/models

Uses only the Python standard library. Exit code 0 when every checkable file is present and identical, 1 otherwise."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify(directory: Path, manifest: dict) -> list:
    """Returns (name, file, status, detail) for each model. Status is ok, missing, wrong-size, wrong-hash or unchecked."""
    rows = []
    for m in manifest["models"]:
        path = directory / m["file"]
        if not m.get("checked") or not m.get("sha256"):
            rows.append((m["name"], m["file"], "unchecked", m["obtain"]))
        elif not path.is_file():
            rows.append((m["name"], m["file"], "missing", m["obtain"]))
        elif path.stat().st_size != m["bytes"]:
            rows.append((m["name"], m["file"], "wrong-size", f"{path.stat().st_size} bytes, expected {m['bytes']}"))
        elif sha256_of(path) != m["sha256"]:
            rows.append((m["name"], m["file"], "wrong-hash", "same size but different content"))
        else:
            rows.append((m["name"], m["file"], "ok", ""))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", type=Path, default=HERE)
    ap.add_argument("--manifest", type=Path, default=HERE / "models.json")
    args = ap.parse_args(argv)
    rows = verify(args.dir, json.loads(args.manifest.read_text(encoding="utf-8")))
    bad = False
    for name, file, status, detail in rows:
        print(f"{status:10s} {file}  ({name})" + (f"\n           {detail}" if detail and status != "ok" else ""))
        bad |= status in {"missing", "wrong-size", "wrong-hash"}
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
