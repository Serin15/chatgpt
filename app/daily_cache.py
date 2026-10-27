"""Bounded daily-report queue; only the child process reads research history.

The separate SQLite file contains disposable, dated report snapshots and sanitized
refresh diagnostics. It is not a backup or a source of research/financial rows.
"""

import asyncio
import hashlib
import json
import sqlite3
import time
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock

from app.models import epoch, utcnow
from app.performance_cache import PerformanceReports

MAX_DAYS = 8
MAX_BYTES = 32 * 1024 * 1024
# Invalidate derived snapshots when the report implementation changes.
REPORT_VERSION = hashlib.sha256(
    b"".join(
        Path(__file__).with_name(name).read_bytes()
        for name in (
            "daily_research.py",
            "daily_cache.py",
            "performance_worker.py",
            "cohort_comparisons.py",
            "forward_evaluation.py",
            "price_research.py",
            "opportunity_outcomes.py",
        )
    )
).hexdigest()


class DailyReports:
    def __init__(self, engine, refresh_seconds=45, stale_seconds=120):
        self.engine = engine
        self.refresh_seconds, self.stale_seconds = refresh_seconds, stale_seconds
        source = engine.store.path.resolve()
        stat = source.stat()
        self.identity = hashlib.sha256(
            f"{source}:{stat.st_dev}:{stat.st_ino}:{REPORT_VERSION}:{engine.service.settings.max_snapshot_age}".encode()
        ).hexdigest()
        self.path = source.parent / "daily-reports.sqlite3"
        self.lock = Lock()
        self.entries, self.pending = OrderedDict(), OrderedDict()
        self.encoded = {}
        self.active = None
        self.persistence_error = None
        self._restore()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=0.2)
        try:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reports(identity TEXT,day TEXT,payload TEXT,at TEXT,PRIMARY KEY(identity,day))"
            )
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _restore(self):
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT day,payload FROM reports WHERE identity=? ORDER BY at DESC LIMIT ?",
                    (self.identity, MAX_DAYS),
                ).fetchall()
            for day, payload in reversed(rows):
                if len(payload.encode("utf-8")) > MAX_BYTES:
                    raise ValueError("Oversized derived report")
                entry = json.loads(payload)
                date.fromisoformat(day)
                if entry.get("data") and entry["data"].get("day_utc") != day:
                    raise ValueError("Mismatched derived report date")
                if entry.get("data"):
                    epoch(entry["data"]["generated_at"])
                    if not isinstance(entry.get("meta"), dict):
                        raise ValueError("Missing derived report metadata")
                    if entry["meta"].get("snapshot_at") != entry["data"]["generated_at"]:
                        raise ValueError("Mismatched derived report timestamp")
                if entry["refresh"]["state"] not in {
                    "not_started",
                    "running",
                    "ok",
                    "interrupted",
                    "error",
                }:
                    raise ValueError("Invalid derived refresh state")
                if entry["refresh"]["state"] == "running":
                    entry["refresh"].update(
                        state="interrupted",
                        error="InterruptedRefresh",
                        last_error="InterruptedRefresh",
                        last_error_at=utcnow(),
                    )
                entry["next_attempt"] = 0
                self.entries[day] = entry
                if entry.get("data"):
                    self.encoded[day] = self._encode(entry["data"])
        except (
            sqlite3.Error,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OSError,
            OverflowError,
        ) as error:
            self.entries.clear()
            self.encoded.clear()
            self.persistence_error = type(error).__name__

    def _persist(self, day, entry):
        try:
            payload = json.dumps(entry, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if len(payload.encode("utf-8")) > MAX_BYTES:
                raise ValueError("Oversized derived report")
            with self._connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO reports VALUES(?,?,?,?)",
                    (self.identity, day, payload, utcnow()),
                )
                db.execute(
                    "DELETE FROM reports WHERE rowid NOT IN (SELECT rowid FROM reports ORDER BY at DESC LIMIT ?)",
                    (MAX_DAYS,),
                )
            self.persistence_error = None
        except (sqlite3.Error, ValueError) as error:
            self.persistence_error = type(error).__name__

    @staticmethod
    def today():
        return datetime.now(UTC).date()

    @staticmethod
    def _encode(data):
        return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )

    def request(self, day, *, schedule_only=False, encoded=False):
        if day > self.today():
            raise ValueError("Alege ziua UTC curentă sau o zi trecută.")
        key, now = day.isoformat(), time.monotonic()
        with self.lock:
            if key not in self.entries:
                if len(self.entries) >= MAX_DAYS:
                    victim = next(
                        (
                            d
                            for d in self.entries
                            if d != self.today().isoformat()
                            and d != self.active
                            and d not in self.pending
                        ),
                        None,
                    )
                    if victim is None:
                        return self._preparing(key, "busy")
                    self.entries.pop(victim)
                    self.encoded.pop(victim, None)
                self.entries[key] = {
                    "data": None,
                    "refresh": {"state": "not_started"},
                    "next_attempt": 0,
                }
            entry = self.entries[key]
            self.entries.move_to_end(key)
            if now >= entry["next_attempt"] and key != self.active:
                self.pending.setdefault(key, None)
            if schedule_only:
                return None
            data = entry["data"]
            refresh = deepcopy(entry["refresh"])
            if key in self.pending:
                refresh["queued"] = True
            if data is None:
                return self._preparing(key, refresh["state"], refresh)
            # Restarts must not give an old report a new 'fresh' timestamp.
            age = time.time() - epoch(data["generated_at"])
            meta = deepcopy(entry["meta"]) | {
                "served_from_cache": True,
                "seconds_since_snapshot": max(0, age),
                "stale": age > self.stale_seconds or age < -5,
                "refresh": refresh,
                "persistence_error": self.persistence_error,
            }
            if encoded:
                return self.encoded[key], meta
            return deepcopy(data) | {"report_state": "ready", "report_cache": meta}

    def http_response(self, day):
        result = self.request(day, encoded=True)
        if isinstance(result, dict):
            return self._encode(result), 202
        body, meta = result
        extra = self._encode({"report_state": "ready", "report_cache": meta})
        # Reuse immutable complete JSON; only the small freshness envelope changes.
        return body[:-1] + (b"," if len(body) > 2 else b"") + extra[1:], 200

    @staticmethod
    def _record(entry):
        # Data/meta are immutable published generations. Copy mutable diagnostics
        # without walking tens of thousands of reference rows on the event loop.
        return dict(entry) | {"refresh": deepcopy(entry["refresh"])}

    def _preparing(self, day, state, refresh=None):
        return {
            "day_utc": day,
            "report_state": "preparing",
            "live_execution": False,
            "detail": "Bilanțul se calculează în fundal. Candidații rămân accesibili.",
            "report_cache": {
                "snapshot_at": None,
                "stale": True,
                "refresh": refresh or {"state": state},
                "persistence_error": self.persistence_error,
            },
        }

    def status(self):
        with self.lock:
            errors = {
                d: deepcopy(e["refresh"])
                for d, e in self.entries.items()
                if e["refresh"].get("last_error") or e["refresh"].get("error")
            }
            return {
                "state": "error"
                if any(e["refresh"]["state"] == "error" for e in self.entries.values())
                else "partial"
                if self.persistence_error
                else "running"
                if self.active
                else "ok",
                "active_day": self.active,
                "queued": len(self.pending),
                "cached_days": [d for d, e in self.entries.items() if e["data"] is not None],
                "diagnostics": errors,
                "persistence_error": self.persistence_error,
            }

    async def calculate_next(self):
        with self.lock:
            if self.active is not None or not self.pending:
                return False
            key, _ = self.pending.popitem(last=False)
            self.active = key
            entry = self.entries[key]
            entry["refresh"].update(state="running", started_at=utcnow(), error=None)
            started = self._record(entry)
        worker = PerformanceReports(self.engine, kind="daily", day=date.fromisoformat(key))
        try:
            await self._save(key, started)
            await worker.calculate_external()
            snapshot = worker.snapshot
            data = snapshot["data"]
            if data["day_utc"] != key:
                raise ValueError("Report day mismatch")
            # Validate before replacing the last complete report.
            encoded = await asyncio.to_thread(self._encode, data)
            if len(encoded) > MAX_BYTES - 8192:
                raise ValueError("Oversized derived report")
            with self.lock:
                entry["data"] = data
                self.encoded[key] = encoded
                entry["meta"] = {
                    "snapshot_at": data["generated_at"],
                    "calculated_at": snapshot["calculated_at"],
                    "calculation_seconds": snapshot["calculation_seconds"],
                    "calculation_mode": "isolated_read_only_process",
                }
                entry["refresh"].update(state="ok", at=utcnow(), error=None)
                entry["next_attempt"] = time.monotonic() + self.refresh_seconds
        except BaseException as error:
            with self.lock:
                at, kind = utcnow(), type(error).__name__
                previous = entry["refresh"]
                entry["refresh"].update(
                    state="interrupted" if isinstance(error, asyncio.CancelledError) else "error",
                    at=at,
                    error=kind,
                    last_error=kind,
                    last_error_at=at,
                    error_history=(previous.get("error_history", []) + [{"at": at, "error": kind}])[
                        -5:
                    ],
                )
                entry["next_attempt"] = time.monotonic() + 15
            if not isinstance(error, Exception):
                raise
        finally:
            with self.lock:
                self.active = None
                final = self._record(entry)
            await self._save(key, final)
        return True

    async def _save(self, key, entry):
        task = asyncio.create_task(asyncio.to_thread(self._persist, key, entry))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def run(self):
        while True:
            self.request(self.today(), schedule_only=True)
            await self.calculate_next()
            await asyncio.sleep(0.5)
