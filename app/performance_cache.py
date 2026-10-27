"""Last complete research report, computed outside HTTP requests and collection."""

import asyncio
import json
import sys
import time
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from threading import Lock

from app.errors import ProviderError
from app.models import utcnow


class PerformanceReports:
    def __init__(self, engine, interval_seconds=45, stale_after_seconds=120, kind="performance", day=None):
        if kind not in {"performance", "routes", "daily"}:
            raise ValueError("Unknown report kind")
        self.engine = engine
        self.kind = kind
        self.day = day
        if kind == "daily" and day is None:
            raise ValueError("Daily report requires a UTC day")
        self.interval_seconds = interval_seconds
        self.stale_after_seconds = stale_after_seconds
        self.lock = Lock()
        self.snapshot = None
        self.refresh = {"state": "not_started"}

    def _begin(self):
        started_at, started = utcnow(), time.monotonic()
        with self.lock:
            if self.refresh["state"] == "running":
                return
            self.refresh = {"state": "running", "started_at": started_at}
        return started_at, started

    def _publish(self, data, clocks, mode):
        started_at, started = clocks
        snapshot = {
            "data": deepcopy(data),
            "generated_at": started_at,
            "calculated_at": utcnow(),
            "monotonic_at": started,
            "completed_monotonic_at": time.monotonic(),
            "calculation_seconds": time.monotonic() - started,
            "calculation_mode": mode,
        }
        with self.lock:
            self.snapshot = snapshot
            self.refresh = {"state": "ok", "at": snapshot["calculated_at"]}

    def _failed(self, error):
        with self.lock:
            self.refresh = {"state": "error", "at": utcnow(), "error": type(error).__name__}

    def calculate(self):
        clocks = self._begin()
        if clocks is None:
            return
        try:
            if self.kind == "daily":
                from app.daily_research import daily_report

                data = daily_report(self.engine, self.day)
            else:
                data = self.engine.routes.report() if self.kind == "routes" else self.engine.report()
        except Exception as error:
            self._failed(error)
            raise
        self._publish(data, clocks, "inline_read_only")

    async def calculate_external(self):
        clocks = self._begin()
        if clocks is None:
            return
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.performance_worker",
                "--database",
                str(self.engine.store.path.resolve()),
                "--news-database",
                str(self.engine.service.news_paper.path.resolve()),
                "--max-snapshot-age",
                str(self.engine.service.settings.max_snapshot_age),
                "--kind",
                self.kind,
                *(["--day", self.day.isoformat()] if self.kind == "daily" else []),
                cwd=str(Path(__file__).resolve().parent.parent),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 180)
            if process.returncode:
                raise ProviderError(
                    "Raportul istoric nu a putut fi calculat în procesul de citire."
                )
            data = json.loads(output.decode("utf-8"))
            self._publish(data, clocks, "isolated_read_only_process")
        except BaseException as error:
            self._failed(error)
            raise
        finally:
            # A finite child never survives normal shutdown. It only reads SQLite,
            # so terminating a cancelled calculation cannot change research rows.
            if process is not None:
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.terminate()
                try:
                    # Drain pipes as well as reaping the child. A cancelled read
                    # may have left a large JSON report in the pipe buffer.
                    await asyncio.wait_for(process.communicate(), 3)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.communicate()

    def read(self):
        with self.lock:
            snapshot, refresh = self.snapshot, deepcopy(self.refresh)
        if snapshot is None:
            raise ProviderError(
                "Raportul istoric se pregătește în fundal. Candidații rămân accesibili; reîncearcă după prima calculare."
                if refresh["state"] != "error"
                else "Raportul istoric nu a putut fi calculat. Verifică starea componentelor și reîncearcă."
            )
        age = max(0, time.monotonic() - snapshot["monotonic_at"])
        return deepcopy(snapshot["data"]) | {
            "generated_at": snapshot["generated_at"],
            "report_cache": {
                "served_from_cache": True,
                "snapshot_at": snapshot["generated_at"],
                "calculated_at": snapshot["calculated_at"],
                "calculation_seconds": snapshot["calculation_seconds"],
                "calculation_mode": snapshot["calculation_mode"],
                "seconds_since_snapshot": age,
                "seconds_since_calculation": max(
                    0, time.monotonic() - snapshot["completed_monotonic_at"]
                ),
                "stale": age > self.stale_after_seconds,
                "refresh": refresh,
            },
        }

    async def run(self):
        while True:
            await self.calculate_external()
            await asyncio.sleep(self.interval_seconds)
