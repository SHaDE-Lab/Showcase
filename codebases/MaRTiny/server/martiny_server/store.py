# Copyright 2026 The SHaDE Lab, Arizona State University
# SPDX-License-Identifier: CERN-OHL-P-2.0
"""Database layer: what MaRTiny stores, and how it is looked after.

Two collections, as in the lab's deployment:
  data    one document per sensor message:  {mac, time (ms since 1970), Temperature, Humidity, ...}
  shadow  one document per analysed photo:  {_id, mac, time (s), boxes, confs, clss, isInShadow, shadow, originalImage, ...}

Store works on a MongoDB database (pymongo) or on MemDb, a small in-memory stand-in that offers the same calls. MemDb
keeps development and the tests independent of a database server; it is not a substitute for MongoDB in production."""
from __future__ import annotations

import math
import re
import time
from typing import Any, Dict, Iterable, List, Optional

READINGS = "data"
RESULTS = "shadow"
# the numeric fields the Arduino sends; anything else in a message is rejected
READING_FIELDS = ("Temperature", "Humidity", "UV_Intensity", "Dallas1", "Dallas2", "Wind_Speed", "Battery_Voltage")
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:_-][0-9A-Fa-f]{2}){5}$")


class ValidationError(ValueError):
    pass


def normalise_mac(mac: Any) -> str:
    """Device ids arrive as 24:6F:28:AA:BB:CC or 24_6F_28_AA_BB_CC; both are stored as upper-case with colons."""
    if not isinstance(mac, str) or not MAC_RE.match(mac):
        raise ValidationError("mac must be a MAC address such as 24:6F:28:AA:BB:CC")
    return re.sub(r"[_-]", ":", mac).upper()


def validate_reading(values: Any) -> Dict[str, Optional[float]]:
    """Keeps only the known fields; each must be a finite number or null."""
    if not isinstance(values, dict):
        raise ValidationError("sensor data must be a JSON object")
    unknown = sorted(set(values) - set(READING_FIELDS))
    if unknown:
        raise ValidationError(f"unknown field(s): {', '.join(unknown)}")
    clean: Dict[str, Optional[float]] = {}
    for key, v in values.items():
        if v is None:
            clean[key] = None
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValidationError(f"{key} must be a number or null")
        else:
            clean[key] = float(v)
    return clean


# ----------------------------------------------------------------------------- in-memory stand-in for pymongo

class _Result:
    def __init__(self, **kw): self.__dict__.update(kw)


def _matches(doc: dict, flt: Optional[dict]) -> bool:
    for key, cond in (flt or {}).items():
        have = doc.get(key)
        if isinstance(cond, dict):
            for op, val in cond.items():
                if op == "$lt" and not (have is not None and have < val): return False
                if op == "$lte" and not (have is not None and have <= val): return False
                if op == "$gt" and not (have is not None and have > val): return False
                if op == "$gte" and not (have is not None and have >= val): return False
                if op == "$ne" and have == val: return False
                if op == "$exists" and (key in doc) != bool(val): return False
                if op not in {"$lt", "$lte", "$gt", "$gte", "$ne", "$exists"}: raise NotImplementedError(op)
        elif have != cond:
            return False
    return True


class _Cursor:
    def __init__(self, docs): self._docs = docs
    def sort(self, key, direction=1):
        if isinstance(key, list): key, direction = key[0]
        self._docs = sorted(self._docs, key=lambda d: (d.get(key) is None, d.get(key)), reverse=direction < 0)
        return self
    def limit(self, n):
        self._docs = self._docs[:n] if n else self._docs
        return self
    def __iter__(self): return iter(self._docs)


class MemCollection:
    """The subset of the pymongo collection API that Store uses."""
    def __init__(self): self.docs: List[dict] = []; self._next = 1
    def insert_one(self, doc):
        doc = dict(doc)
        if "_id" not in doc: doc["_id"] = self._next; self._next += 1
        if any(d["_id"] == doc["_id"] for d in self.docs): raise KeyError(f"duplicate _id {doc['_id']!r}")
        self.docs.append(doc); return _Result(inserted_id=doc["_id"])
    def find(self, flt=None, projection=None):
        out = [d for d in self.docs if _matches(d, flt)]
        if projection:
            keep = {k for k, v in projection.items() if v}
            out = [{k: v for k, v in d.items() if k in keep or k == "_id"} for d in out]
        return _Cursor([dict(d) for d in out])
    def find_one(self, flt=None):
        return next(iter(self.find(flt).limit(1)), None)
    def distinct(self, key, flt=None):
        return sorted({d[key] for d in self.docs if key in d and _matches(d, flt)})
    def count_documents(self, flt=None): return sum(1 for d in self.docs if _matches(d, flt))
    def delete_many(self, flt):
        keep = [d for d in self.docs if not _matches(d, flt)]
        n = len(self.docs) - len(keep); self.docs = keep; return _Result(deleted_count=n)
    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if _matches(d, flt):
                for k, v in update.get("$set", {}).items(): d[k] = v
                for k in update.get("$unset", {}): d.pop(k, None)
                n += 1
        return _Result(modified_count=n, matched_count=n)
    def create_index(self, keys, **kw): return "_".join(f"{k}_{d}" for k, d in keys)


class MemDb:
    def __init__(self): self._c: Dict[str, MemCollection] = {}
    def __getitem__(self, name): return self._c.setdefault(name, MemCollection())


def connect(settings):
    """Store on the MongoDB named in the settings, or on memory when MONGO_URL is not set."""
    if not settings.mongo_url:
        return Store(MemDb())
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError("MONGO_URL is set but pymongo is not installed (pip install pymongo)") from exc
    return Store(MongoClient(settings.mongo_url)[settings.mongo_db])


# ----------------------------------------------------------------------------- the store

class Store:
    def __init__(self, db): self.db = db

    # ----- writing
    def insert_reading(self, mac: Any, values: Any, now_ms: Optional[int] = None) -> dict:
        doc = validate_reading(values)
        doc["mac"] = normalise_mac(mac)
        doc["time"] = int(now_ms if now_ms is not None else time.time() * 1000)
        self.db[READINGS].insert_one(doc)
        return doc

    def insert_result(self, doc: dict) -> None:
        self.db[RESULTS].insert_one(doc)

    # ----- reading (newest first, by time, so it does not depend on insertion order)
    def device_ids(self) -> List[str]:
        return sorted(self.db[READINGS].distinct("mac"))

    def latest_readings(self, mac: Optional[str] = None, limit: int = 10) -> List[dict]:
        flt = {"mac": normalise_mac(mac)} if mac else {}
        return list(self.db[READINGS].find(flt).sort("time", -1).limit(max(1, min(int(limit), 1000))))

    def latest_result(self, mac: Optional[str] = None) -> Optional[dict]:
        flt = {"mac": normalise_mac(mac)} if mac else {}
        found = list(self.db[RESULTS].find(flt).sort("time", -1).limit(1))
        return found[0] if found else None

    # ----- looking after the database
    def ensure_indexes(self) -> None:
        """Queries ask for the newest documents of one device, so index on (mac, time)."""
        for name in (READINGS, RESULTS):
            self.db[name].create_index([("mac", 1), ("time", -1)])

    def stats(self) -> dict:
        out: Dict[str, Any] = {}
        for name in (READINGS, RESULTS):
            coll = self.db[name]
            times = [d["time"] for d in coll.find({}, {"time": 1}) if "time" in d]
            devices = {m: coll.count_documents({"mac": m}) for m in coll.distinct("mac")}
            out[name] = {"documents": coll.count_documents({}), "devices": devices,
                         "oldest": min(times) if times else None, "newest": max(times) if times else None}
        return out

    def prune(self, readings_before_ms: Optional[int] = None, results_before_s: Optional[int] = None, dry_run: bool = False) -> dict:
        """Deletes sensor readings older than a time (milliseconds) and/or photo results older than a time (seconds)."""
        plan = {READINGS: ({"time": {"$lt": readings_before_ms}} if readings_before_ms is not None else None),
                RESULTS: ({"time": {"$lt": results_before_s}} if results_before_s is not None else None)}
        done = {}
        for name, flt in plan.items():
            if flt is None: continue
            done[name] = self.db[name].count_documents(flt) if dry_run else self.db[name].delete_many(flt).deleted_count
        return done

    def strip_images(self, before_s: int, dry_run: bool = False) -> dict:
        """Keeps the counts but removes the stored photographs and shadow maps older than a time (seconds), for privacy and
        space. Returns how many documents lost each field. It filters in the database, so no image is loaded into memory."""
        out = {}
        coll = self.db[RESULTS]
        for field in ("shadow", "originalImage"):
            flt = {"time": {"$lt": before_s}, field: {"$exists": True}}
            out[field] = coll.count_documents(flt) if dry_run else coll.update_many(flt, {"$unset": {field: ""}}).modified_count
        return out

    def export(self, collection: str, flt: Optional[dict] = None, limit: int = 0) -> Iterable[dict]:
        if collection not in (READINGS, RESULTS):
            raise ValidationError(f"collection must be {READINGS!r} or {RESULTS!r}")
        proj = None if collection == READINGS else {k: 1 for k in ("_id", "mac", "time", "readableTime", "boxes", "confs", "clss", "isInShadow")}
        return self.db[collection].find(flt or {}, proj).sort("time", 1).limit(limit)
