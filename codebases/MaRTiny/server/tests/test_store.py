import pytest

from martiny_server.store import (MemDb, RESULTS, READINGS, Store, ValidationError, normalise_mac, validate_reading)

MAC1, MAC2 = "24:6F:28:AA:BB:01", "24:6F:28:AA:BB:02"
DAY_MS = 86400 * 1000


def test_mac_forms_are_normalised():
    assert normalise_mac("24_6f_28_aa_bb_cc") == "24:6F:28:AA:BB:CC"
    assert normalise_mac("24-6F-28-AA-BB-CC") == "24:6F:28:AA:BB:CC"
    assert normalise_mac("24:6F:28:AA:BB:CC") == "24:6F:28:AA:BB:CC"


@pytest.mark.parametrize("bad", ["", "nonsense", "24:6F:28:AA:BB", "24:6F:28:AA:BB:CC:DD", "../../etc", None, 5, {"$ne": ""}, ["24:6F:28:AA:BB:CC"]])
def test_bad_device_ids_are_rejected(bad):
    with pytest.raises(ValidationError):
        normalise_mac(bad)


def test_reading_fields_are_checked():
    assert validate_reading({"Temperature": 31, "Humidity": None, "Wind_Speed": 2.5}) == {"Temperature": 31.0, "Humidity": None, "Wind_Speed": 2.5}
    for bad in ({"Temperature": "hot"}, {"Temperature": float("nan")}, {"Temperature": float("inf")}, {"Temperature": True},
                {"Temperature": {"$gt": 0}}, {"Surprise": 1}, [], "text", None):
        with pytest.raises(ValidationError):
            validate_reading(bad)


def test_insert_reading_adds_device_and_time():
    s = Store(MemDb())
    doc = s.insert_reading("24_6F_28_AA_BB_01", {"Temperature": 30.5}, now_ms=1234)
    assert doc["mac"] == MAC1 and doc["time"] == 1234 and doc["Temperature"] == 30.5
    assert s.db[READINGS].find_one({"mac": MAC1})["time"] == 1234


def test_a_rejected_reading_is_not_stored():
    s = Store(MemDb())
    with pytest.raises(ValidationError):
        s.insert_reading(MAC1, {"Temperature": "x"})
    assert s.db[READINGS].count_documents({}) == 0


def test_latest_readings_are_newest_first_by_time_not_insertion_order():
    s = Store(MemDb())
    for t in (300, 100, 200):
        s.insert_reading(MAC1, {"Temperature": t}, now_ms=t)
    s.insert_reading(MAC2, {"Temperature": 999}, now_ms=400)
    assert [d["time"] for d in s.latest_readings(MAC1)] == [300, 200, 100]
    assert [d["time"] for d in s.latest_readings(MAC1, limit=2)] == [300, 200]
    assert s.latest_readings()[0]["mac"] == MAC2                 # no id: all devices
    assert s.device_ids() == [MAC1, MAC2]


def test_query_cannot_be_hijacked_with_an_object():
    s = Store(MemDb())
    s.insert_reading(MAC1, {"Temperature": 1}, now_ms=1)
    with pytest.raises(ValidationError):
        s.latest_readings({"$ne": ""})


def test_latest_result_picks_the_newest_for_a_device():
    s = Store(MemDb())
    s.insert_result({"_id": "a", "mac": MAC1, "time": 10})
    s.insert_result({"_id": "b", "mac": MAC1, "time": 30})
    s.insert_result({"_id": "c", "mac": MAC2, "time": 99})
    assert s.latest_result(MAC1)["_id"] == "b" and s.latest_result()["_id"] == "c"
    assert Store(MemDb()).latest_result() is None


def filled():
    s = Store(MemDb())
    now_s = 1_700_000_000
    for age_days in (400, 200, 5, 1):
        t = now_s - age_days * 86400
        s.insert_reading(MAC1, {"Temperature": age_days}, now_ms=t * 1000)
        s.insert_result({"_id": f"r{age_days}", "mac": MAC1, "time": t, "isInShadow": [1], "shadow": "x" * 10, "originalImage": "y" * 10})
    return s, now_s


def test_stats():
    s, now_s = filled()
    st = s.stats()
    assert st[READINGS]["documents"] == 4 and st[READINGS]["devices"] == {MAC1: 4}
    assert st[RESULTS]["oldest"] == now_s - 400 * 86400 and st[RESULTS]["newest"] == now_s - 86400


def test_prune_dry_run_changes_nothing_and_real_run_deletes_old_data_only():
    s, now_s = filled()
    cut = now_s - 100 * 86400
    assert s.prune(cut * 1000, cut, dry_run=True) == {READINGS: 2, RESULTS: 2}
    assert s.db[READINGS].count_documents({}) == 4
    assert s.prune(cut * 1000, cut) == {READINGS: 2, RESULTS: 2}
    assert [d["time"] for d in s.latest_readings(MAC1)] == [(now_s - 86400) * 1000, (now_s - 5 * 86400) * 1000]
    assert s.prune() == {}                                         # nothing asked, nothing deleted


def test_readings_use_milliseconds_and_results_use_seconds():
    s, now_s = filled()
    s.prune(readings_before_ms=(now_s - 100 * 86400) * 1000)       # only readings
    assert s.db[RESULTS].count_documents({}) == 4 and s.db[READINGS].count_documents({}) == 2


def test_strip_images_keeps_the_counts():
    s, now_s = filled()
    cut = now_s - 100 * 86400
    assert s.strip_images(cut, dry_run=True) == {"shadow": 2, "originalImage": 2}
    assert "shadow" in s.db[RESULTS].find_one({"_id": "r400"})
    assert s.strip_images(cut) == {"shadow": 2, "originalImage": 2}
    old, new = s.db[RESULTS].find_one({"_id": "r400"}), s.db[RESULTS].find_one({"_id": "r1"})
    assert "shadow" not in old and "originalImage" not in old and old["isInShadow"] == [1]
    assert new["shadow"] == "x" * 10                               # recent photos untouched
    assert s.strip_images(cut) == {"shadow": 0, "originalImage": 0}  # repeating is harmless


def test_export_rejects_unknown_collections_and_leaves_images_out():
    s, _ = filled()
    with pytest.raises(ValidationError):
        s.export("users")
    rows = list(s.export(RESULTS))
    assert len(rows) == 4 and all("shadow" not in r and "originalImage" not in r for r in rows)
    assert [r["time"] for r in rows] == sorted(r["time"] for r in rows)
    assert len(list(s.export(READINGS, {"mac": MAC1}, limit=2))) == 2


def test_ensure_indexes_is_repeatable():
    s = Store(MemDb()); s.ensure_indexes(); s.ensure_indexes()
