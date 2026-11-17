import csv
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import db_admin  # noqa: E402

from martiny_server.store import MemDb, READINGS, RESULTS, Store  # noqa: E402

MAC = "24:6F:28:AA:BB:01"
NOW = 1_700_000_000


@pytest.fixture
def store():
    s = Store(MemDb())
    for age in (400, 200, 5, 1):
        t = NOW - age * 86400
        s.insert_reading(MAC, {"Temperature": float(age), "Humidity": None}, now_ms=t * 1000)
        s.insert_result({"_id": f"r{age}", "mac": MAC, "time": t, "boxes": [[1, 2, 3, 4]], "isInShadow": [1], "shadow": "s", "originalImage": "o"})
    return s


def run(store, *argv):
    out = io.StringIO()
    code = db_admin.run(list(argv), store, out=out, now=NOW)
    return code, out.getvalue()


def test_stats_prints_json(store):
    code, text = run(store, "stats")
    st = json.loads(text)
    assert code == 0 and st[READINGS]["documents"] == 4 and st[RESULTS]["devices"] == {MAC: 4}


def test_indexes(store):
    assert "indexes ready" in run(store, "indexes")[1]


def test_prune_dry_run_then_real(store):
    _, text = run(store, "prune", "--days", "100", "--dry-run")
    assert text.startswith("would delete") and json.loads(text.split("delete ", 1)[1]) == {READINGS: 2, RESULTS: 2}
    assert store.db[READINGS].count_documents({}) == 4
    _, text = run(store, "prune", "--days", "100")
    assert text.startswith("deleted") and store.db[READINGS].count_documents({}) == 2 and store.db[RESULTS].count_documents({}) == 2


def test_strip_images(store):
    _, text = run(store, "strip-images", "--days", "100")
    assert json.loads(text.split("removed ", 1)[1]) == {"shadow": 2, "originalImage": 2}
    assert "shadow" not in store.db[RESULTS].find_one({"_id": "r400"}) and "shadow" in store.db[RESULTS].find_one({"_id": "r1"})


def test_export_csv_and_json(store, tmp_path):
    csv_path, json_path = tmp_path / "data.csv", tmp_path / "results.json"
    assert "wrote 4 rows" in run(store, "export", READINGS, "--out", str(csv_path))[1]
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 4 and rows[0]["mac"] == MAC and float(rows[0]["Temperature"]) == 400.0
    run(store, "export", RESULTS, "--out", str(json_path), "--mac", MAC, "--limit", "2")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 2 and "originalImage" not in data[0] and "shadow" not in data[0]


def test_unknown_command_and_missing_option_exit_with_usage_error(store):
    for argv in (["bogus"], ["prune"]):
        with pytest.raises(SystemExit) as e:
            run(store, *argv)
        assert e.value.code == 2
