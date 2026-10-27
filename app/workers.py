"""Supervise workers while retaining bounded, sanitized recovery diagnostics."""

import asyncio
import logging

from app.models import utcnow

log = logging.getLogger(__name__)


async def supervise(name, fn, workers, retry_seconds=5):
    record = workers[name] = {
        "state": "running", "started_at": utcnow(), "restarts": 0, "error": None,
        "last_error": None, "last_error_at": None, "error_history": [],
    }
    try:
        while True:
            try:
                await fn()
                raise RuntimeError("Worker returned unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                at, kind = utcnow(), type(error).__name__
                record.update(state="error", error=kind, last_error=kind, last_error_at=at)
                record["restarts"] += 1
                record["error_history"] = (record["error_history"] + [{"at": at, "error": kind}])[-5:]
                # Arbitrary exception messages may contain URLs, credentials or file paths.
                log.warning("Background worker %s failed (%s); retrying.", name, kind)
                await asyncio.sleep(retry_seconds)
                record.update(state="running", error=None)
    finally:
        record.update(state="stopped", error=None)
